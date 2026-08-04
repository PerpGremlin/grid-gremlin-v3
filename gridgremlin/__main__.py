import argparse
import sys

from .main import run


def main():
    p = argparse.ArgumentParser(prog='gridgremlin')
    p.add_argument('config')
    p.add_argument('--cycles', type=int, default=None)
    p.add_argument('--interval', type=float, default=None)
    p.add_argument('--snapshot', default=None)
    p.add_argument('--snapshot-every', type=int, default=60)
    args = p.parse_args()
    return run(args.config, cycles=args.cycles, poll_seconds=args.interval,
               snapshot=args.snapshot, snapshot_every=args.snapshot_every)


if __name__ == '__main__':
    sys.exit(main())
