# Fleet build and run (SPEC E8, F1-F5, I2, I3, C5, C6). No mainnet path.
import fcntl
import json
import time
from pathlib import Path

from .apply import bot_identity, check_fleet_unique, check_link_fits
from .adapters import adapter_for
from .bot import Bot
from .config import ConfigError, check_placeable, validate_fleet
import os

from .events import Notifier, TelegramNotifier
from .exchange.bybit.client import WriteClient
from .exchange.bybit.truth import parse_instrument, read_wallet
from .exchange.env import load_env
from .ladder import grid_rungs, position_cap
from .watchdog import validate_watchdog

BYBIT_LINK_LIMIT = 36
CEILING_MULTIPLE = 1.5      # F2: a watchdog ceiling beyond this is decorative


def refuse_mainnet(client):
    """F5: there is no mainnet path in v3 — not a flag, an absence."""
    if client.env == 'mainnet':
        raise ConfigError('v3 has no mainnet path — refuse (D19/F5)')


def check_watchdog_coverage(bots_caps, watchdog_cfg):
    """F1 both ways; F2 ceilings pinned near the cap."""
    watched = set(watchdog_cfg['positions'])
    fleet_ids = {botid for botid, _ in bots_caps}
    for botid, cap in bots_caps:
        if botid not in watched:
            raise ConfigError(f'{botid} is not in the watchdog config — '
                              'nothing trades unwatched (F1)')
        if cap is not None:
            ceiling = watchdog_cfg['positions'][botid]['max']
            if not cap <= ceiling <= cap * CEILING_MULTIPLE:
                raise ConfigError(
                    f'{botid}: watchdog ceiling {ceiling:.10g} must sit in '
                    f'[{cap:.10g}, {cap * CEILING_MULTIPLE:.10g}] — a breach '
                    'should mean the cap itself failed (F2)')
    for botid in watched - fleet_ids:
        raise ConfigError(f"watchdog watches '{botid}' which is not in the "
                          'fleet — stale entry (F1)')


def acquire_fleet_lock(path):
    """F3: one fleet process per account, enforced, not remembered."""
    handle = open(path, 'w')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise ConfigError(f'another fleet process holds {path} — one fleet '
                          'per account, ever (F3)')
    return handle


def snapshot_row(bots, wallet, now):
    """F4/E3: derived from venue truth only; the DEAD are visible."""
    return {'t': now, 'equity': wallet['equity'], 'mm_rate': wallet['mm_rate'],
            'bots': {b.botid: {'alive': b.alive,
                               'position': b._last_pos or 0.0}
                     for b in bots}}


def build_fleet(fleet_path, notifier):
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    client = WriteClient()
    refuse_mainnet(client)
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
    if fleet.get('watchdog'):
        wd = validate_watchdog(json.loads(Path(fleet['watchdog']).read_text()))
        caps = [(b.botid,
                 position_cap(b.cfg, b.adapter, grid_rungs(b.cfg, b.adapter))
                 if b.cfg['strategy'] == 'grid' else None)
                for b in bots]
        check_watchdog_coverage(caps, wd)
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


def make_notifier():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if token and chat:
        return TelegramNotifier(token, chat)
    return Notifier()


def run(fleet_path, cycles=None, poll_seconds=None, ship_orders=None,
        snapshot=None, snapshot_every=60, lock_path=None):
    load_env()
    notifier = make_notifier()
    fleet, client, bots = build_fleet(fleet_path, notifier)
    lock = acquire_fleet_lock(lock_path
                              or f'/tmp/gridgremlin.{client.env}.lock')
    try:
        notifier.ship_orders = (fleet['notify_orders'] if ship_orders is None
                                else ship_orders)
        poll = poll_seconds or fleet['poll_seconds']
        n = 0
        while cycles is None or n < cycles:
            wallet = read_wallet(client.wallet_balance())          # E8
            for bot in bots:
                counts = bot.cycle(equity=wallet['equity'])
                if counts is not None:
                    print(f"cycle {n} {bot.botid}: {counts}", flush=True)
            if snapshot and n % snapshot_every == 0:
                row = snapshot_row(bots, wallet, time.time())
                with open(snapshot, 'a') as f:
                    f.write(json.dumps(row) + '\n')
            if not any(b.alive for b in bots):
                print('all bots dead — fleet exits', flush=True)
                return 0
            n += 1
            if cycles is None or n < cycles:
                time.sleep(poll)
        return 0
    finally:
        if hasattr(notifier, 'close'):
            notifier.close()
        lock.close()
