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
from .exchange.errors import VenueError
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
    clients, bots, identities = {}, [], []
    for cfg in fleet['bots']:
        venue = cfg['venue']
        if venue not in clients:
            if venue == 'hyperliquid':
                from .exchange.hyperliquid.venue import HLVenueClient
                clients[venue] = HLVenueClient()      # testnet-only (F5)
            else:
                clients[venue] = WriteClient()
                refuse_mainnet(clients[venue])
        client = clients[venue]
        if venue == 'hyperliquid':
            entry = next(e for e in client.meta()['universe']
                         if e['name'] == cfg['symbol'])
            from .exchange.hyperliquid.truth import parse_instrument as hl_pi
            spec = hl_pi(entry)
            from .exchange.hyperliquid.adapters import HLPerpAdapter
            adapter = HLPerpAdapter(spec)
        else:
            spec = parse_instrument(cfg['market_type'],
                                    client.instruments_info(cfg['market_type'],
                                                            cfg['symbol']))
            adapter = adapter_for(cfg['market_type'], spec)
        cfg['funding_interval_minutes'] = spec['funding_interval_minutes']
        check_placeable(cfg, adapter)
        bot = Bot(cfg, adapter, client, notifier, gen_seed=int(time.time()))
        limit = 16 if venue == 'hyperliquid' else BYBIT_LINK_LIMIT
        chars = 4 if venue == 'hyperliquid' else 10
        check_link_fits(bot.botid, cfg.get('rungs', 99), limit, gen_chars=chars)
        identities.append((bot.botid, bot_identity(cfg, adapter)))
        if venue == 'bybit' and cfg['market_type'] == 'linear':
            client.ensure_hedge_mode(cfg['market_type'], cfg['symbol'])
        elif venue == 'hyperliquid':
            try:
                client.update_leverage(client._entry(cfg['symbol'])[0],
                                       int(cfg['leverage']))
            except VenueError as e:
                notifier.event('warn', cfg['symbol'],
                               f'leverage assert deferred (venue hiccup): {e}')
        bots.append(bot)
    _ensure_symbol_capacity(clients, bots, notifier)
    check_fleet_unique(identities)
    if not fleet.get('watchdog'):
        raise ConfigError("the fleet has no 'watchdog' config — nothing "
                          'trades unwatched (F1)')
    if fleet.get('watchdog'):
        wd = validate_watchdog(json.loads(Path(fleet['watchdog']).read_text()))
        caps = [(b.botid,
                 position_cap(b.cfg, b.adapter, grid_rungs(b.cfg, b.adapter))
                 if b.cfg['strategy'] == 'grid' else None)
                for b in bots]
        check_watchdog_coverage(caps, wd)
    envs = ', '.join(f'{v}:{c.env}' for v, c in clients.items())
    notifier.event('fleet', 'fleet',
                   f'{len(bots)} bot(s) on {envs}: '
                   + ', '.join(b.botid for b in bots))
    _project_margin(clients, fleet['bots'], notifier)
    return fleet, clients, bots


def _ensure_symbol_capacity(clients, bots, notifier):
    """Hedge-aware, ONCE per (venue, symbol): the risk tier fits the SUM of
    both legs' ladders (a small hedge leg must never downgrade the big one —
    the 110048 incident), and buy/sell leverage are set per leg."""
    groups = {}
    for b in bots:
        if b.cfg['venue'] == 'bybit' and b.cfg['market_type'] == 'linear':
            groups.setdefault(b.cfg['symbol'], []).append(b)
    for symbol, legs in groups.items():
        client = legs[0].client
        need = sum(b.cfg['ladder_notional'] for b in legs)
        tiers = client.risk_limit_tiers('linear', symbol)
        tier = next((t for t in tiers if need <= t['limit']), tiers[-1])
        for idx in {legs and 1, 2} & {1, 2}:
            try:
                client.set_risk_limit('linear', symbol, tier['id'], idx)
            except Exception as e:
                notifier.event('warn', symbol, f'risk limit: {e}')
        # the venue requires buy lv == sell lv (10001): one symbol leverage,
        # the max of the legs — margin-cheapest; ladder sizes come from config
        levs = []
        for b in legs:
            lev = min(b.cfg['leverage'], tier['max_leverage'] or b.cfg['leverage'])
            if lev != b.cfg['leverage']:
                notifier.event('warn', symbol,
                               f"{b.botid}: leverage clamped "
                               f"{b.cfg['leverage']:g} -> {lev:g} (tier max at "
                               f'{need:,.0f} symbol notional)')
                b.cfg['leverage'] = lev
            levs.append(lev)
            b.cfg['_tier_mm_rate'] = tier['mm_rate']
        symbol_lev = max(levs)
        if len(set(levs)) > 1:
            notifier.event('warn', symbol,
                           f'legs configured {sorted(set(levs))} but the venue '
                           f'requires equal buy/sell leverage — using '
                           f'{symbol_lev:g} for both (sizes unaffected)')
        client.set_leverage('linear', symbol, symbol_lev)


def _project_margin(clients, cfgs, notifier):
    equity = sum(c.read_wallet()['equity'] for c in clients.values())
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
    fleet, clients, bots = build_fleet(fleet_path, notifier)
    lock_tag = '+'.join(f'{v}.{c.env}' for v, c in sorted(clients.items()))
    lock = acquire_fleet_lock(lock_path or f'/tmp/gridgremlin.{lock_tag}.lock')
    try:
        notifier.ship_orders = (fleet['notify_orders'] if ship_orders is None
                                else ship_orders)
        poll = poll_seconds or fleet['poll_seconds']
        n = 0
        while cycles is None or n < cycles:
            wallets = {v: c.read_wallet() for v, c in clients.items()}   # E8
            wallet = {'equity': sum(w['equity'] for w in wallets.values()),
                      'mm_rate': max((w['mm_rate'] or 0.0)
                                     for w in wallets.values())}
            for bot in bots:
                counts = bot.cycle(equity=wallets[bot.cfg['venue']]['equity'])
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
