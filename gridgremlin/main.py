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
            _ensure_capacity(client, cfg, adapter, notifier)
        bots.append(bot)
    check_fleet_unique(identities)
    notifier.event('fleet', 'fleet',
                   f"{len(bots)} bot(s) on {client.env}: "
                   + ', '.join(b.botid for b in bots))
    _project_margin(client, fleet['bots'], notifier)
    return fleet, client, bots


def _ensure_capacity(client, cfg, adapter, notifier):
    """Risk-limit tier to fit the full ladder; symbol leverage to the config's,
    clamped to the tier's max. The worst case is typed before trading."""
    tiers = client.risk_limit_tiers(cfg['market_type'], cfg['symbol'])
    need = cfg['ladder_notional']
    tier = next((t for t in tiers if need <= t['limit']), tiers[-1])
    idx = adapter.position_idx('Buy' if cfg['side'] == 'long' else 'Sell', False)
    try:
        client.set_risk_limit(cfg['market_type'], cfg['symbol'],
                              tier['id'], idx or 0)
    except Exception as e:
        notifier.event('warn', cfg['symbol'], f'risk limit: {e}')
    lev = min(cfg['leverage'], tier['max_leverage'] or cfg['leverage'])
    if lev != cfg['leverage']:
        notifier.event('warn', cfg['symbol'],
                       f"leverage clamped {cfg['leverage']:g} -> {lev:g} "
                       f"(tier max at {need:,.0f} notional)")
        cfg['leverage'] = lev
    client.set_leverage(cfg['market_type'], cfg['symbol'], lev)
    cfg['_tier_mm_rate'] = tier['mm_rate']


def _project_margin(client, cfgs, notifier):
    equity = read_wallet(client.wallet_balance())['equity']
    if not equity:
        return
    mm = sum(c['ladder_notional'] * c.get('_tier_mm_rate', 0.005)
             for c in cfgs if c['market_type'] != 'spot')
    im = sum(c['capital'] for c in cfgs)
    notifier.event('fleet', 'fleet',
                   f'projected full-deployment: MM {mm / equity:.1%} of equity, '
                   f'IM {im / equity:.1%}')


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
            if counts is not None:
                print(f"cycle {n} {bot.botid}: {counts}", flush=True)
        if not any(b.alive for b in bots):
            print('all bots dead — fleet exits', flush=True)
            return 0
        n += 1
        if cycles is None or n < cycles:
            time.sleep(poll)
    return 0
