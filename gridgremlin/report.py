# The readout (SPEC R1-R5): venue fills -> per-bot grid profit vs total P&L
# (D8's reporting model). Read-only by construction — no write client in this
# module's import graph (R4). Usage:
#   python3 -m gridgremlin.report <fleet.json> [--hours N]
import json
import sys
import time
from pathlib import Path

from .apply import make_botid, rung_of
from .config import validate_fleet
from .exchange.env import load_env
from .exchange.errors import VenueError

EPS = 1e-12
HL_FILL_CAP = 2000


def owner_of(link_id, botids):
    """R1: a fill is a bot's iff rung_of parses under that botid (I1)."""
    for botid in botids:
        if rung_of(link_id, botid) is not None:
            return botid
    return None


def new_book():
    return {'fills': 0, 'bought': 0.0, 'sold': 0.0, 'realized': 0.0,
            'fees': 0.0, 'position': 0.0, 'avg_cost': 0.0, 'inverse': False}


def apply_fill(book, side, price, qty, fee, inverse=False):
    """R2: average-cost accounting — a reduce realises, a flip re-anchors.
    A4's unit law holds here too: an inverse book realises in the BASE coin
    (qty is $1 contracts), a linear/spot book in the quote coin."""
    signed = qty if side == 'buy' else -qty
    pos = book['position']
    book['inverse'] = inverse
    if abs(pos) < EPS or (pos > 0) == (signed > 0):
        total = abs(pos) + qty
        book['avg_cost'] = (book['avg_cost'] * abs(pos) + price * qty) / total
        book['position'] = pos + signed
    else:
        closed = min(abs(pos), qty)
        held = 1.0 if pos > 0 else -1.0
        if inverse:
            book['realized'] += closed * (1.0 / book['avg_cost']
                                          - 1.0 / price) * held
        else:
            book['realized'] += (price - book['avg_cost']) * closed * held
        book['position'] = pos + signed
        if qty - closed > EPS:
            book['avg_cost'] = price
        elif abs(book['position']) < EPS:
            book['position'], book['avg_cost'] = 0.0, 0.0
    book['fees'] += fee
    book['fills'] += 1
    book['bought' if side == 'buy' else 'sold'] += qty
    return book


def ledger(fills, botids, inverse_ids=()):
    """R1/R3: time-ordered fills -> books keyed by botid, or by
    ('unowned', symbol) — external activity is reported, never dropped."""
    books = {}
    for f in sorted(fills, key=lambda f: f['time_ms']):
        key = owner_of(f['link_id'], botids) or ('unowned', f['symbol'])
        apply_fill(books.setdefault(key, new_book()),
                   f['side'], f['price'], f['qty'], f['fee'],
                   inverse=key in inverse_ids)
    return books


def unreal_pnl(book, mark):
    """Mark-to-average on the open remainder, in the book's own coin (A4)."""
    if abs(book['position']) < EPS:
        return 0.0
    if mark is None:
        return None
    if book.get('inverse'):
        return book['position'] * (1.0 / book['avg_cost'] - 1.0 / mark)
    return (mark - book['avg_cost']) * book['position']


def total_pnl(book, mark):
    """R5: grid profit (realized - fees) plus mark-to-average on the open
    remainder; an unknown mark yields None, never a guess. Inverse books
    are BASE-coin throughout and convert to quote AT MARK for display."""
    net = book['realized'] - book['fees']
    u = unreal_pnl(book, mark)
    if u is None:
        return None
    total = net + u
    if book.get('inverse'):
        return total * mark if mark is not None else None
    return total


# --- venue pulls (reads only) ------------------------------------------------

def _bybit_pull(rows, since_ms, now_ms):
    from .exchange.bybit.client import Client
    from .exchange.bybit.truth import read_fills
    client = Client()
    fills, marks = [], {}
    for category, symbol in sorted({(r['market_type'], r['symbol'])
                                    for r in rows}):
        fills += read_fills(client, category, symbol, since_ms, now_ms)
        try:
            # the CLIENT method, not the raw reader — it knows spot truth
            # needs the instrument's base coin (V6)
            marks[symbol] = client.read_symbol_truth(category,
                                                     symbol)['mark']
        except (VenueError, OSError):
            marks[symbol] = None
    return fills, marks


def _hl_pull(rows, since_ms):
    from .exchange.hyperliquid.client import InfoClient
    from .exchange.hyperliquid.truth import read_fills, read_symbol_truth
    client = InfoClient()
    coins = sorted({r['symbol'] for r in rows})
    raw = client.user_fills_by_time(since_ms)
    if len(raw) >= HL_FILL_CAP:
        print(f'[warn] HL answered its {HL_FILL_CAP}-fill cap — the window '
              'is truncated, narrow --hours', file=sys.stderr)
    fills = read_fills(raw, set(coins))
    marks = {}
    for coin in coins:
        try:
            marks[coin] = read_symbol_truth(client, coin)['mark']
        except (VenueError, OSError):
            marks[coin] = None
    return fills, marks


# --- the table ---------------------------------------------------------------

def _n(v, nd=2):
    return '—' if v is None else f'{v:,.{nd}f}'


def _row(name, book, mark):
    inv = book.get('inverse')
    scale = (mark if inv and mark is not None else 1.0)
    unreal = unreal_pnl(book, mark)
    if inv and mark is None:
        unreal = None
    open_at = ('flat' if abs(book['position']) < EPS
               else f"{book['position']:.10g}@{book['avg_cost']:,.6g}")
    def usd(v):
        return None if v is None else v * scale
    return (f"{name:<18}{book['fills']:>6}"
            f"{_n(usd(book['realized'])):>12}{_n(usd(book['fees'])):>10}"
            f"{open_at:>20}{_n(usd(unreal)):>12}"
            f"{_n(total_pnl(book, mark)):>12}")


def main(argv):
    hours = 24.0
    if '--hours' in argv:
        i = argv.index('--hours')
        hours = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 1:
        print('usage: python3 -m gridgremlin.report <fleet.json> [--hours N]')
        return 2
    load_env()
    fleet = validate_fleet(json.loads(Path(argv[0]).read_text()))
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - int(hours * 3600 * 1000)
    by_venue, symbol_of, inverse_ids = {}, {}, set()
    for cfg in fleet['bots']:
        by_venue.setdefault(cfg['venue'], []).append(cfg)
        botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        symbol_of[botid] = cfg['symbol']
        if cfg['market_type'] == 'inverse':
            inverse_ids.add(botid)
    botids = list(symbol_of)
    fills, marks = [], {}
    for venue, rows in sorted(by_venue.items()):
        try:
            got, m = (_hl_pull(rows, since_ms) if venue == 'hyperliquid'
                      else _bybit_pull(rows, since_ms, now_ms))
        except (VenueError, OSError) as e:
            print(f'[warn] {venue}: unreachable, skipped — {e}',
                  file=sys.stderr)
            continue
        fills += got
        marks.update(m)
    books = ledger(fills, botids, inverse_ids)
    print(f'last {hours:g}h · grid profit = realized − fees (D8) · '
          f'total adds mark-to-average on the open remainder')
    print(f"{'bot':<18}{'fills':>6}{'realized':>12}{'fees':>10}"
          f"{'open@avg':>20}{'unreal':>12}{'total':>12}")
    for botid in botids:
        book = books.get(botid)
        if book is None:
            print(f'{botid:<18}{0:>6}{"—":>12}{"—":>10}{"—":>20}'
                  f'{"—":>12}{"—":>12}')
            continue
        print(_row(botid, book, marks.get(symbol_of[botid])))
    for key in sorted(k for k in books if isinstance(k, tuple)):
        _, symbol = key
        print(_row(f'unowned {symbol}', books[key], marks.get(symbol)))
    owned = [b for k, b in books.items() if not isinstance(k, tuple)]
    if owned:
        realized = sum(b['realized'] for b in owned)
        fees = sum(b['fees'] for b in owned)
        print(f"{'TOTAL (owned)':<18}{sum(b['fills'] for b in owned):>6}"
              f'{_n(realized):>12}{_n(fees):>10}{"":>20}{"":>12}'
              f'{_n(realized - fees):>12}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
