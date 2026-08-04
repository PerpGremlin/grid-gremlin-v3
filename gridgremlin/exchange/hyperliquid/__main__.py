# Live read check: python3 -m gridgremlin.exchange.hyperliquid COIN
# Reads only; prints market data and schema verdicts, never account figures.
import sys

from ..env import load_env
from .client import InfoClient
from .truth import parse_instrument, read_symbol_truth, read_wallet


def main(argv):
    coin = argv[0] if argv else 'BTC'
    load_env()
    client = InfoClient()
    print(f'env: {client.env}')
    entry = next(e for e in client.meta()['universe'] if e['name'] == coin)
    spec = parse_instrument(entry)
    print(f"instrument: {coin} qty_step {spec['qty_step']} "
          f"sz_decimals {spec['sz_decimals']}")
    t = read_symbol_truth(client, coin)
    print(f"truth: mark {t['mark']} bid {t['bid']} ask {t['ask']} "
          f"split_ref {t['split_ref']} funding/h {t['funding_rate_hourly']:.3e}")
    print(f"orders: {len(t['orders'])} resting; positions: {sorted(t['positions'])}")
    read_wallet(client.clearinghouse_state())
    print('wallet: schema OK')
    print('truth: schema OK')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
