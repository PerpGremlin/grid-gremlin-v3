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
from .ladder import fee_floor_for
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


def closer_of(fill, closers):
    """R7: a fill the VENUE created to close a position (hosted TP/SL,
    trailing, liquidation) carries no link — the venue says what it is, and
    I2 says exactly one bot owns (market, symbol, side), so the fill belongs
    to the bot whose exits sit on that side. Evidence, not inference."""
    if not fill.get('venue_closed'):
        return None
    return closers.get((fill.get('market_type'), fill['symbol'],
                        fill['side']))


def new_book():
    return {'fills': 0, 'first_side': None,
            'bought': 0.0, 'sold': 0.0, 'realized': 0.0,
            'fees': 0.0, 'position': 0.0, 'avg_cost': 0.0, 'inverse': False,
            # R6 — the activity layer, same fills, no new state:
            'trips': 0,            # realisation events (a grid's round trips)
            'rounds': 0,           # flat crossings (a martingale's rounds)
            'round_pnl_sum': 0.0,  # realized per completed round, summed
            'so_fills': 0,         # entry fills at rung >= 1 (safety orders)
            'same_rung': 0,        # R9: exits filled at a price we BOUGHT at
            '_entry_px': set(),    # prices this book has entered at
            'max_depth': 0,        # deepest safety rung ever reached
            '_round_realized0': 0.0, '_round_depth': 0}


def apply_fill(book, side, price, qty, fee, inverse=False, rung=None,
               entry_side=None):
    """R2: average-cost accounting — a reduce realises, a flip re-anchors.
    A4's unit law holds here too: an inverse book realises in the BASE coin
    (qty is $1 contracts), a linear/spot book in the quote coin.
    R6: the same stream carries the activity — a realisation is a TRIP, a
    flat crossing closes a ROUND, an entry fill at rung >= 1 is a SAFETY
    order and its rung is the round's depth."""
    signed = qty if side == 'buy' else -qty
    pos = book['position']
    prev_avg = book['avg_cost']   # R9 reads the pre-fill cost
    if book['first_side'] is None:
        book['first_side'] = side
    book['inverse'] = inverse
    if entry_side is not None and side == entry_side and rung and rung >= 1:
        book['so_fills'] += 1
        book['_round_depth'] = max(book['_round_depth'], rung)
        book['max_depth'] = max(book['max_depth'], book['_round_depth'])
    if abs(pos) < EPS or (pos > 0) == (signed > 0):
        total = abs(pos) + qty
        book['avg_cost'] = (book['avg_cost'] * abs(pos) + price * qty) / total
        book['position'] = pos + signed
    else:
        closed = min(abs(pos), qty)
        held = 1.0 if pos > 0 else -1.0
        book['trips'] += 1
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
            book['rounds'] += 1                       # a flat crossing
            book['round_pnl_sum'] += (book['realized']
                                      - book['_round_realized0'])
            book['_round_realized0'] = book['realized']
            book['_round_depth'] = 0
    # R9: the zero-spread signature is an exit whose margin against the
    # cost it closes is inside the fee. The first cut compared against a
    # lifetime set of every entry price — grids REUSE a fixed lattice, so
    # profitable full-gap trips flagged whenever a later round exited where
    # an earlier one entered (audit 2026-08-07 H1: two profitable bots
    # chased). The margin is per-exit, against this book's own average.
    entering = (abs(pos) < EPS or (pos > 0) == (signed > 0))
    if not entering and abs(pos) >= EPS and prev_avg > 0:
        margin = (price - prev_avg) * (1.0 if pos > 0 else -1.0)
        if abs(margin) / prev_avg < 0.0005:   # inside a spot fee
            book['same_rung'] += 1
    book['fees'] += fee
    book['fills'] += 1
    book['bought' if side == 'buy' else 'sold'] += qty
    return book


def ledger(fills, botids, inverse_ids=(), entry_sides=None, closers=None):
    """R1/R3: time-ordered fills -> books keyed by botid, or by
    ('unowned', symbol) — external activity is reported, never dropped.
    R6: rung and entry side ride along so the activity layer can count.
    R7: venue-created closes attribute by the position they closed."""
    books, entry_sides = {}, entry_sides or {}
    closers = closers or {}
    for f in sorted(fills, key=lambda f: f['time_ms']):
        key = (owner_of(f['link_id'], botids) or closer_of(f, closers)
               or ('unowned', f['symbol']))
        rung = rung_of(f['link_id'], key) if isinstance(key, str) else None
        apply_fill(books.setdefault(key, new_book()),
                   f['side'], f['price'], f['qty'], f['fee'],
                   inverse=key in inverse_ids, rung=rung,
                   entry_side=entry_sides.get(key))
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
            marks[(category, symbol)] = client.read_symbol_truth(
                category, symbol)['mark']
        except (VenueError, OSError):
            marks[(category, symbol)] = None
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
            marks[('linear', coin)] = read_symbol_truth(client, coin)['mark']
        except (VenueError, OSError):
            marks[('linear', coin)] = None
    return fills, marks


# --- the table ---------------------------------------------------------------

def _n(v, nd=2):
    return '—' if v is None else f'{v:,.{nd}f}'


def window_truncated(book, side):
    """R7: a window that opens MID-round sees the close but not the open, so
    the ledger's remainder contradicts the bot's own direction. Say so —
    never print a phantom position as if it were real."""
    if side is None:
        return False
    # a balanced slice nets the phantom away and the sign test passes it
    # (audit 2026-08-07 MED): the window's FIRST fill is the other tell —
    # a one-sided book cannot legitimately open with its exit side
    first = book.get('first_side')
    if first and (first == ('sell' if side == 'long' else 'buy')):
        return True
    if abs(book['position']) < EPS:
        return False
    return (book['position'] < 0) if side == 'long' else (book['position'] > 0)


def _row(name, book, mark, side=None):
    inv = book.get('inverse')
    scale = (mark if inv and mark is not None else 1.0)
    unreal = unreal_pnl(book, mark)
    if inv and mark is None:
        unreal = None
    cut = window_truncated(book, side)
    open_at = ('flat' if abs(book['position']) < EPS
               else f"{book['position']:.10g}@{book['avg_cost']:,.6g}")
    if cut:
        open_at = 'pre-window*'
    def usd(v):
        return None if v is None else v * scale
    return (f"{name:<18}{book['fills']:>6}"
            f"{_n(usd(book['realized'])):>12}{_n(usd(book['fees'])):>10}"
            f"{open_at:>20}{_n(usd(unreal)):>12}"
            f"{_n(total_pnl(book, mark)):>12}")


def _watchdog_view(fleet):
    """The watcher, watched (F1/F2): each bot's ceiling, and how long ago
    the watchdog last swept — its state file's own mtime, so a dead timer
    shows as a growing number instead of a silence."""
    path = fleet.get('watchdog')
    if not path:
        return None
    try:
        wd = json.loads(Path(path).read_text())
        ceilings = {b: v.get('max') for b, v in
                    (wd.get('positions') or {}).items()}
        swept = None
        state = wd.get('state')
        if state and Path(state).exists():
            swept = max(0, int(time.time() - Path(state).stat().st_mtime))
        belief = {}
        snap = wd.get('snapshot')
        if snap and Path(snap).exists():
            lines = Path(snap).read_text().strip().splitlines()
            if lines:
                row = json.loads(lines[-1])
                belief = {'age_s': max(0, int(time.time() - row.get('t', 0))),
                          'bots': row.get('bots', {})}
        return {'ceilings': ceilings, 'swept_s_ago': swept,
                'belief': belief}
    except (OSError, ValueError):
        return None


def public_book(book, mark=None, side=None, strategy=None):
    """The data contract, one book: every public field of the ledger, plus
    what a renderer needs and nothing it must compute. Private working
    state (underscore keys, sets) never leaves this module — the panel and
    the terminal table read THIS, so they can never disagree (D8/R7)."""
    out = {k: v for k, v in book.items()
           if not k.startswith('_') and not isinstance(v, set)}
    out['mark'] = mark
    out['side'] = side
    out['strategy'] = strategy
    out['truncated'] = window_truncated(book, side)
    if out['truncated']:
        out['same_rung'] = None    # a margin against a partial average is
                                   # not a verdict (R9 honours R7)
    unreal = None
    if mark is not None and abs(book['position']) > 1e-12 \
            and book['avg_cost'] > 0 and not book.get('inverse'):
        unreal = (mark - book['avg_cost']) * book['position']
    out['unreal_at_mark'] = unreal
    return out


def main(argv):
    hours = 24.0
    as_json = '--json' in argv
    if as_json:
        argv = [a for a in argv if a != '--json']
    if '--hours' in argv:
        i = argv.index('--hours')
        hours = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 1:
        print('usage: python3 -m gridgremlin.report <fleet.json> [--hours N] [--json]')
        return 2
    load_env()
    fleet = validate_fleet(json.loads(Path(argv[0]).read_text()))
    now_ms = int(time.time() * 1000)
    since_ms = now_ms - int(hours * 3600 * 1000)
    by_venue, key_of, inverse_ids = {}, {}, set()
    strat_of, entry_sides, closers, side_of = {}, {}, {}, {}
    range_of = {}
    for cfg in fleet['bots']:
        by_venue.setdefault(cfg['venue'], []).append(cfg)
        botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        key_of[botid] = (cfg['market_type'], cfg['symbol'])
        strat_of[botid] = cfg.get('strategy', 'grid')
        entry_sides[botid] = 'buy' if cfg['side'] == 'long' else 'sell'
        side_of[botid] = cfg['side']
        if cfg.get('lower') and cfg.get('upper'):
            range_of[botid] = {'lower': cfg['lower'], 'upper': cfg['upper'],
                               'rungs': cfg.get('rungs')}
        exit_side = 'sell' if cfg['side'] == 'long' else 'buy'
        closers[(cfg['market_type'], cfg['symbol'], exit_side)] = botid
        if cfg['market_type'] == 'inverse':
            inverse_ids.add(botid)
            inverse_ids.add(('unowned', cfg['symbol']))
    botids = list(key_of)
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
    books = ledger(fills, botids, inverse_ids, entry_sides, closers)
    if as_json:
        contract = {
            'window_hours': hours,
            'generated_ms': now_ms,
            'bots': {b: (public_book(books[b], marks.get(key_of[b]),
                                     side_of.get(b), strat_of.get(b))
                         if b in books else None)   # quiet ≠ absent: every
                     for b in botids},              # configured bot appears
            'ranges': range_of,
            'watchdog': _watchdog_view(fleet),
            'fee_floors': {b: fee_floor_for(key_of[b][0]) for b in botids},
            'unowned': {k[1]: public_book(books[k])
                        for k in books if isinstance(k, tuple)
                        and k[0] == 'unowned'}}
        print(json.dumps(contract))
        return 0
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
        print(_row(botid, book, marks.get(key_of[botid]),
                   side=side_of.get(botid)))
    for key in sorted(k for k in books if isinstance(k, tuple)
                      and k[0] == 'unowned'):
        _, symbol = key
        mark = next((m for (cat, sym), m in marks.items()
                     if sym == symbol and m is not None), None)
        print(_row(f'unowned {symbol}', books[key], mark))
    if any(window_truncated(b, side_of.get(k))
           for k, b in books.items() if isinstance(k, str)):
        print("* the window opened mid-round: that bot's realized and "
              "remainder are partial — widen --hours for the whole story")
    # A4 in miniature: 'quote' is not one currency — totals group by the
    # symbol's actual quote coin, one row each (audit 2026-08-07 LOW)
    by_quote = {}
    for k, b in books.items():
        if isinstance(k, tuple) or b.get('inverse'):
            continue
        sym = key_of.get(k, (None, ''))[1]
        q = next((c for c in ('USDT', 'USDC', 'USD', 'EUR', 'BTC')
                  if sym.endswith(c)), 'quote')
        by_quote.setdefault(q, []).append(b)
    for q, owned in sorted(by_quote.items()):
        realized = sum(b['realized'] for b in owned)
        fees = sum(b['fees'] for b in owned)
        print(f"{f'TOTAL ({q})':<18}{sum(b['fills'] for b in owned):>6}"
              f'{_n(realized):>12}{_n(fees):>10}{"":>20}{"":>12}'
              f'{_n(realized - fees):>12}')
    print()
    print(f"{'— activity —':<18}{'trips':>7}{'per-trip':>10}"
          f"{'rounds':>8}{'avg/round':>11}{'SO fills':>10}{'max depth':>11}{'bought':>12}{'sold':>12}")
    for botid in botids:
        b = books.get(botid)
        if b is None or b['fills'] == 0:
            continue
        if strat_of.get(botid) == 'martingale':
            avg = (b['round_pnl_sum'] / b['rounds']) if b['rounds'] else None
            wash = (f"  <- {b['same_rung']} ZERO-SPREAD exit(s) (R9)"
                    if b['same_rung']
                    and not window_truncated(b, side_of.get(botid)) else '')
            print(f"{botid:<18}{'—':>7}{'—':>10}{b['rounds']:>8}"
                  f"{_n(avg):>11}{b['so_fills']:>10}{b['max_depth']:>11}"
                  f"{_n(b['bought']):>12}{_n(b['sold']):>12}{wash}")
        else:
            per = (b['realized'] / b['trips']) if b['trips'] else None
            wash = (f"  <- {b['same_rung']} ZERO-SPREAD exit(s) (R9)"
                    if b['same_rung']
                    and not window_truncated(b, side_of.get(botid)) else '')
            print(f"{botid:<18}{b['trips']:>7}{_n(per):>10}"
                  f"{'—':>8}{'—':>11}{'—':>10}{'—':>11}"
                  f"{_n(b['bought']):>12}{_n(b['sold']):>12}{wash}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
