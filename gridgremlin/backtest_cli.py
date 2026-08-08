# Composition glue (like main.py — venue names are allowed here, A6): fresh
# venue bars into the pure backtest core.
#   python3 -m gridgremlin.backtest_cli <fleet.json> --bot <botid>
#           [--days 7] [--bar-minutes 60] [--fee 0.0002] [--funding 0]
import json
import sys
import time
from pathlib import Path

from .adapters import adapter_for
from .apply import make_botid
from .backtest import backtest
from .config import validate_fleet


def rehearse(draft, bars, adapter, fee=0.0002, bar_minutes=60):
    """§9: a draft config replayed over real bars, returning the same
    vocabulary as the readout plus the hold benchmark — what the same
    capital did just sitting there. Pure: candles in, verdict out."""
    r = backtest(draft, adapter, bars, fee_rate=fee,
                 funding_rate_hourly=0.0, bar_hours=bar_minutes / 60.0)
    first_o, last_c = bars[0]['o'], bars[-1]['c']
    sign = 1.0 if draft['side'] == 'long' else -1.0
    r['hold_benchmark'] = draft['capital'] * sign * (last_c / first_o - 1.0)
    r['bars'] = len(bars)
    r['first_open'], r['last_close'] = first_o, last_c
    return r


def draft_guards(draft):
    """The CLI's venue/strategy guards, one place, same words for every
    author (UI, file, agent) — a refusal is the engine speaking."""
    if draft.get('venue', 'bybit') != 'bybit':
        return "no kline fetcher for venue '%s' yet — Bybit only" % \
            draft.get('venue')
    if draft.get('strategy', 'grid') == 'martingale':
        return 'the backtester replays plan_grid — grids only (T3)'
    if draft.get('market_type') != 'linear':
        return ("the backtester's fee/PnL maths are linear-only — '%s' "
                'would return confident nonsense (A4)'
                % draft.get('market_type'))
    return None


def run_draft(raw, days, bar_minutes, fee):
    """--draft: validate a config that exists nowhere yet, fetch real
    bars, rehearse. Returns a dict; 'refused' carries the engine's own
    refusal text verbatim."""
    from .config import ConfigError, validate_grid
    try:
        draft = validate_grid(json.loads(raw))
    except (ConfigError, ValueError) as e:
        return {'refused': str(e)}
    why = draft_guards(draft)
    if why:
        return {'refused': why}
    from .exchange.bybit.klines import fetch_bars, fetch_instrument
    from .exchange.bybit.truth import parse_instrument
    adapter = adapter_for(draft['market_type'], parse_instrument(
        draft['market_type'],
        fetch_instrument(draft['market_type'], draft['symbol'])))
    now = int(time.time() * 1000)
    bars = fetch_bars(draft['market_type'], draft['symbol'], bar_minutes,
                      now - int(days * 86_400_000), now)
    if not bars:
        return {'refused': 'no bars returned — check the symbol and window'}
    return rehearse(draft, bars, adapter, fee=fee, bar_minutes=bar_minutes)


def main(argv):
    def opt(name, default):
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        return default

    botid = opt('--bot', None)
    as_draft = '--draft' in argv
    if as_draft:
        argv.remove('--draft')
    days = float(opt('--days', '7'))
    bar_minutes = int(opt('--bar-minutes', '60'))
    fee = float(opt('--fee', '0.0002'))
    funding = float(opt('--funding', '0'))
    if as_draft:
        out = run_draft(sys.stdin.read(), float(opt('--days', '7')),
                        int(opt('--bar-minutes', '60')),
                        float(opt('--fee', '0.0002')))
        print(json.dumps(out))
        return 0 if 'refused' not in out else 1
    if len(argv) != 1 or not botid:
        print('usage: python3 -m gridgremlin.backtest_cli <fleet.json> '
              '--bot <botid> [--days 7] [--bar-minutes 60] [--fee 0.0002] '
              '[--funding 0]')
        return 2
    fleet = validate_fleet(json.loads(Path(argv[0]).read_text()))
    cfg = next((b for b in fleet['bots']
                if make_botid(b['market_type'], b['symbol'], b['side'])
                == botid), None)
    if cfg is None:
        known = [make_botid(b['market_type'], b['symbol'], b['side'])
                 for b in fleet['bots']]
        print(f'{botid}: not in this fleet — bots: {", ".join(known)}')
        return 2
    if cfg.get('venue') != 'bybit':
        print(f"{botid}: no kline fetcher for venue '{cfg.get('venue')}' yet "
              '— Bybit bots only')
        return 2
    if cfg.get('strategy') == 'martingale':
        print(f'{botid}: the backtester replays plan_grid — grids only (T3)')
        return 2
    if cfg['market_type'] != 'linear':
        print(f"{botid}: the backtester's fee/PnL maths are linear-only — "
              f"'{cfg['market_type']}' would return confident nonsense (A4)")
        return 2
    from .exchange.bybit.klines import fetch_bars, fetch_instrument
    from .exchange.bybit.truth import parse_instrument
    adapter = adapter_for(cfg['market_type'], parse_instrument(
        cfg['market_type'], fetch_instrument(cfg['market_type'],
                                             cfg['symbol'])))
    now = int(time.time() * 1000)
    bars = fetch_bars(cfg['market_type'], cfg['symbol'], bar_minutes,
                      now - int(days * 86_400_000), now)
    if not bars:
        print('no bars returned — check the symbol and window')
        return 1
    r = backtest(cfg, adapter, bars, fee_rate=fee,
                 funding_rate_hourly=funding, bar_hours=bar_minutes / 60.0)
    print(f'{botid}: {len(bars)} bars x {bar_minutes}m over {days:g}d')
    print(f"  grid profit {r['grid_profit']:,.2f}  fees {r['fees']:,.2f}  "
          f"funding {r['funding']:,.2f}  net {r['net']:,.2f}")
    print(f"  total (incl. open) {r['total']:,.2f}  "
          f"max drawdown {r['max_drawdown']:,.2f}")
    print(f"  {r['trips']} exit trips / {r['entry_fills']} entry fills;  "
          f"ends holding {r['held']:.10g}"
          + (f" @ {r['basis']:,.6g}" if r['basis'] else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
