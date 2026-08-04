# Live truth check: python3 -m gridgremlin.exchange.bybit SYMBOL [market_type]
# Reads and schema-validates truth from the resolved environment. Prints no
# secrets, no account figures beyond what the operator asked to see.
import sys

from ..env import load_env
from .client import Client
from .truth import parse_instrument, read_symbol_truth, read_wallet


def main(argv):
    symbol = argv[0] if argv else 'BTCUSDT'
    market_type = argv[1] if len(argv) > 1 else 'linear'
    load_env()
    client = Client()
    print(f'env: {client.env}')
    spec = parse_instrument(market_type,
                            client.instruments_info(market_type, symbol))
    print(f"instrument: {spec['symbol']} tick {spec['price_tick']} "
          f"step {spec['qty_step']} min_qty {spec['min_qty']} "
          f"funding_interval_min {spec['funding_interval_minutes']}")
    t = read_symbol_truth(client, market_type, symbol,
                          spec['funding_interval_minutes'])
    print(f"truth: mark {t['mark']} bid {t['bid']} ask {t['ask']} "
          f"split_ref {t['split_ref']:.2f} "
          f"funding/h {t['funding_rate_hourly']:.3e}")
    print(f"orders: {len(t['orders'])} resting; "
          f"positions: {sorted(t['positions'])}")
    w = read_wallet(client.wallet_balance())
    print(f"wallet: schema OK ({len(w['coins'])} coins)")
    print('truth: schema OK')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
