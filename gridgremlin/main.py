# Fleet build and run (SPEC E8, I2, I3, C5, C6). No mainnet path exists in v3.
import json
import time
from pathlib import Path

from .apply import bot_identity, check_fleet_unique, check_link_fits
from .adapters import adapter_for
from .bot import Bot
from .config import ConfigError, check_placeable, validate_fleet
from .events import Notifier
from .exchange.bybit.client import WriteClient
from .exchange.bybit.truth import parse_instrument, read_wallet
from .exchange.env import load_env

BYBIT_LINK_LIMIT = 36


def build_fleet(fleet_path, notifier):
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    client = WriteClient()
    if client.env == 'mainnet':
        raise ConfigError('v3 has no mainnet path — refuse (D19/F5)')
    bots, identities = [], []
    for cfg in fleet['bots']:
        spec = parse_instrument(cfg['market_type'],
                                client.instruments_info(cfg['market_type'],
                                                        cfg['symbol']))
        cfg['funding_interval_minutes'] = spec['funding_interval_minutes']
        adapter = adapter_for(cfg['market_type'], spec)
        check_placeable(cfg, adapter)
        bot = Bot(cfg, adapter, client, notifier, gen_seed=int(time.time()))
        check_link_fits(bot.botid, cfg.get('rungs', 99), BYBIT_LINK_LIMIT)
        identities.append((bot.botid, bot_identity(cfg, adapter)))
        if cfg['market_type'] == 'linear':
            client.ensure_hedge_mode(cfg['market_type'], cfg['symbol'])
        bots.append(bot)
    check_fleet_unique(identities)
    notifier.event('fleet', 'fleet',
                   f"{len(bots)} bot(s) on {client.env}: "
                   + ', '.join(b.botid for b in bots))
    return fleet, client, bots


def run(fleet_path, cycles=None, poll_seconds=None, ship_orders=None):
    notifier = Notifier()
    fleet, client, bots = build_fleet(fleet_path, notifier)
    notifier.ship_orders = (fleet['notify_orders'] if ship_orders is None
                            else ship_orders)
    poll = poll_seconds or fleet['poll_seconds']
    n = 0
    while cycles is None or n < cycles:
        read_wallet(client.wallet_balance())          # E8: fail loudly, early
        for bot in bots:
            counts = bot.cycle()
            print(f"cycle {n} {bot.botid}: {counts}", flush=True)
        n += 1
        if cycles is None or n < cycles:
            time.sleep(poll)
    return 0
