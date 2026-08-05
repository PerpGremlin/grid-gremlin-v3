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


def main(argv):
    def opt(name, default):
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        return default

    botid = opt('--bot', None)
    days = float(opt('--days', '7'))
    bar_minutes = int(opt('--bar-minutes', '60'))
    fee = float(opt('--fee', '0.0002'))
    funding = float(opt('--funding', '0'))
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
