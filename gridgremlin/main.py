# Fleet build and run (SPEC E8, F1-F7, I2, I3, C5, C6). Mainnet is
# double-safetied (F7), never an accident.
import fcntl
import json
import time
from pathlib import Path

from .apply import bot_identity, check_fleet_unique, check_link_fits
from .adapters import adapter_for
from .bot import Bot
from .config import (ConfigError, VENUE_ICONS, check_placeable,
                     validate_fleet)
import os

from .events import Notifier, TelegramNotifier, VenueNotifier
from .exchange.bybit.client import WriteClient
from .exchange.bybit.truth import parse_instrument, read_wallet
from .exchange.errors import VenueError
from .exchange.env import load_env
from .ladder import grid_rungs, position_cap
from .tombstones import Tombstones, TombstoneError
from .watchdog import validate_watchdog

BYBIT_LINK_LIMIT = 36
CEILING_MULTIPLE = 1.5      # F2: a watchdog ceiling beyond this is decorative


def refuse_mainnet(client, fleet_allows=False, run_allows=False):
    """F7 (D25): mainnet fires only with BOTH safeties off — the fleet file
    declares `"allow_mainnet": true` (reviewed, committed intent) AND the
    launch passes `--allow-mainnet` (operator intent, per start). Either
    alone refuses. The demo/testnet env flags are the helmet; this is the
    armour — a cloned repo cannot reach real money by accident."""
    if client.env != 'mainnet':
        return
    missing = []
    if not fleet_allows:
        missing.append('\'"allow_mainnet": true\' in the fleet file')
    if not run_allows:
        missing.append('--allow-mainnet on the launch')
    if missing:
        raise ConfigError('mainnet is double-safetied (D25) — missing '
                          + ' AND '.join(missing))


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


def _vn(notifier, venue):
    """Label a fleet-level event with its venue for the phone (owner ask)."""
    return VenueNotifier(notifier, VENUE_ICONS.get(venue, ''))


def preflight_verdict(failures, tolerance):
    """F8's policy, pure: within tolerance the failed bots stay dead-and-
    visible; beyond it the fleet refuses, naming every failure (D7/D27)."""
    if len(failures) > tolerance:
        listed = '; '.join(f'{b}: {r}' for b, r in failures)
        raise ConfigError(
            f'preflight failed for {len(failures)} bot(s) '
            f'(tolerance {tolerance}) — {listed}')


def probe_bot(bot):
    """F8: the dress rehearsal — one unfillable post-only order at a far
    price on the ENTRY side, resting proves the whole placement path (auth,
    permissions, collateral, lot rules), then it is cancelled. Returns None
    on success, the venue's reason on failure."""
    cfg, adapter, client = bot.cfg, bot.adapter, bot.client
    try:
        truth = client.read_symbol_truth(
            cfg['market_type'], cfg['symbol'],
            cfg.get('funding_interval_minutes', 480.0))
        mark = truth['mark']
        far = mark * (0.7 if cfg['side'] == 'long' else 1.3)
        price = adapter.round_price(far)
        floor_notional = (adapter.min_notional or 0.0) * 1.05
        qty = adapter.round_qty(max(
            adapter.min_qty,
            adapter.qty_from_notional(floor_notional, price)
            if floor_notional else adapter.min_qty))
        bot._gen += 1
        r = client.place_order(
            cfg['market_type'], cfg['symbol'], bot._entry_side,
            adapter.fmt_qty(qty), adapter.fmt_price(price),
            bot._make_link(0),
            adapter.position_idx(bot._entry_side, False) or 0,
            reduce_only=False, post_only=True,
            borrow=bool(cfg.get('spot_borrow')))
        oid = (r or {}).get('orderId') or (r or {}).get('oid')
        if oid is not None:
            try:
                client.cancel_order(cfg['market_type'], cfg['symbol'], oid)
            except VenueError as e:
                if e.kind != 'gone':
                    raise
        return None
    except Exception as e:                                   # noqa: BLE001
        return f'{type(e).__name__}: {e}'   # one bot fails, not the build


def build_fleet(fleet_path, notifier, allow_mainnet=False):
    load_env()
    fleet = validate_fleet(json.loads(Path(fleet_path).read_text()))
    try:
        tombs = Tombstones(fleet.get('tombstones') or 'logs/tombstones.json')
    except TombstoneError as e:
        raise ConfigError(str(e)) from e
    clients, bots, identities = {}, [], []
    for cfg in fleet['bots']:
        venue = cfg['venue']
        if venue not in clients:
            armed = fleet.get('allow_mainnet', False) and allow_mainnet
            if venue == 'hyperliquid':
                from .exchange.hyperliquid.venue import HLVenueClient
                clients[venue] = HLVenueClient(allow_mainnet=armed)
            else:
                clients[venue] = WriteClient()
            refuse_mainnet(clients[venue], fleet.get('allow_mainnet', False),
                           allow_mainnet)
        client = clients[venue]
        if venue == 'hyperliquid':
            # _entry refuses BY NAME — a coin the venue removed must say so
            # (the XRP testnet delisting crashed the build as StopIteration)
            _, entry = client._entry(cfg['symbol'])
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
        if cfg.get('strategy') != 'martingale':
            # G16: the venue's own fee schedule vs this grid's own spacing —
            # a grid that cannot clear its round trip loses on every trip,
            # and nothing else in the build would ever say so.
            rates = getattr(client, 'fee_rates', None)
            if rates is not None:
                try:
                    from .ladder import grid_rungs as _g16, trip_economics
                    maker = rates(cfg['market_type'], cfg['symbol'])['maker']
                    net, gap, trip = trip_economics(_g16(cfg, adapter), maker)
                    if net is not None and net <= 0:
                        _vn(notifier, venue).event(
                            'warn', cfg['symbol'],
                            f'EVERY ROUND TRIP LOSES: rung gap {gap:.4%} vs '
                            f'round-trip fee {trip:.4%} — widen the range or '
                            f'cut rungs (G16)')
                    elif net is not None and net < trip:
                        _vn(notifier, venue).event(
                            'warn', cfg['symbol'],
                            f'thin margin: rung gap {gap:.4%} barely clears '
                            f'the {trip:.4%} round trip (net {net:.4%}/trip)')
                except (VenueError, OSError, KeyError, TypeError):
                    pass
            # B8 was pinned as a pure function and never wired to a call site
            # (audit 2026-08-06): a grid whose gap sits inside the guard band
            # churns forever, silently. It needs LIVE quotes, so it lands
            # here — stated loudly, not refused on a transient spread.
            try:
                from .ladder import (SPACING_GUARD_MULTIPLE,
                                     grid_rungs as _gr,
                                     spacing_clears_guard)
                t = client.read_symbol_truth(
                    cfg['market_type'], cfg['symbol'],
                    spec['funding_interval_minutes'])
                ok, gap, guard = spacing_clears_guard(
                    _gr(cfg, adapter), t['bid'], t['ask'])
                # the guard scales with the LIVE spread, so a grid sitting
                # within a few percent of the threshold flips either way
                # between restarts — warn on a real shortfall, not on noise
                if not ok and gap < 0.95 * SPACING_GUARD_MULTIPLE * guard:
                    _vn(notifier, venue).event(
                        'warn', cfg['symbol'],
                        f'rung gap {gap:.10g} sits inside the cross guard '
                        f'({guard:.10g}, needs '
                        f'{SPACING_GUARD_MULTIPLE * guard:.10g}) — nearest '
                        'rungs will be dropped; widen the range or cut '
                        'rungs (B8)')
            except (VenueError, OSError, KeyError, TypeError):
                pass                    # a quote we cannot read is not a verdict
        if (cfg.get('spot_borrow')
                and spec.get('margin_trading') not in (None, 'both',
                                                       'utaOnly')):
            # F8's metadata half: the venue's own catalogue says this coin
            # cannot margin-trade — ask what CAN be asked (D27)
            cfg['_preflight_fail'] = (f"venue catalogue: marginTrading="
                                      f"'{spec.get('margin_trading')}' — "
                                      'this coin cannot borrow')
        check_placeable(cfg, adapter)
        bot = Bot(cfg, adapter, client, notifier, gen_seed=int(time.time()),
                  tombstones=tombs)
        if tombs.has(bot.botid):
            # X7: a fired stop survives the process. Dead AND visible (F4);
            # revival = the operator deletes the tombstone entry, on purpose.
            bot.alive = False
            _vn(notifier, venue).event('warn', bot.botid,
                           'tombstoned — a stop fired '
                           f'({tombs.reason(bot.botid)}); remove the entry '
                           f"from {fleet.get('tombstones') or 'logs/tombstones.json'} "
                           'to revive, deliberately')
        limit = 16 if venue == 'hyperliquid' else BYBIT_LINK_LIMIT
        chars = 4 if venue == 'hyperliquid' else 10
        check_link_fits(bot.botid, cfg.get('rungs', 99), limit, gen_chars=chars)
        identities.append((bot.botid, bot_identity(cfg, adapter)))
        if venue == 'bybit' and cfg['market_type'] == 'linear':
            client.ensure_hedge_mode(cfg['market_type'], cfg['symbol'])
        elif (venue == 'bybit' and cfg['market_type'] == 'spot'
                and cfg.get('spot_borrow')):
            try:
                client.ensure_collateral(spec['base_coin'])
            except VenueError as e:
                _vn(notifier, venue).event('warn', cfg['symbol'],
                                           f'collateral switch deferred: {e}')
        elif venue == 'hyperliquid':
            try:
                client.update_leverage(client._entry(cfg['symbol'])[0],
                                       int(cfg['leverage']))
            except VenueError as e:
                _vn(notifier, venue).event(
                    'warn', cfg['symbol'],
                    f'leverage assert deferred (venue hiccup): {e}')
        bots.append(bot)
    _ensure_symbol_capacity(clients, bots, notifier)
    check_fleet_unique(identities)
    pf = fleet.get('preflight') or {'probe': False, 'max_failed_bots': 0}
    failures = []
    for b in bots:
        if not b.alive:
            continue                       # tombstoned: already dead-visible
        reason = b.cfg.pop('_preflight_fail', None)
        if reason is None and pf.get('probe'):
            reason = probe_bot(b)
        if reason is not None:
            failures.append((b.botid, reason))
            b.alive = False
            _vn(notifier, b.cfg['venue']).event(
                'warn', b.botid, f'preflight FAILED — building dead: {reason}')
    preflight_verdict(failures, pf.get('max_failed_bots', 0))
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
    fleet_n = (_vn(notifier, next(iter(clients))) if len(clients) == 1
               else notifier)                     # single-venue fleet: labeled
    fleet_n.event('fleet', 'fleet',
                  f'{len(bots)} bot(s) on {envs}: '
                  + ', '.join(b.botid for b in bots))
    _project_margin(clients, fleet['bots'], fleet_n)
    return fleet, clients, bots


def _ensure_symbol_capacity(clients, bots, base_notifier):
    """Hedge-aware, ONCE per (venue, symbol): the risk tier fits the SUM of
    both legs' ladders (a small hedge leg must never downgrade the big one —
    the 110048 incident), and buy/sell leverage are set per leg."""
    notifier = _vn(base_notifier, 'bybit')       # this function IS bybit-only
    groups = {}
    for b in bots:
        if b.cfg['venue'] == 'bybit' and b.cfg['market_type'] == 'linear':
            groups.setdefault(b.cfg['symbol'], []).append(b)
    for symbol, legs in groups.items():
        client = legs[0].client
        need = sum(b.cfg['ladder_notional'] for b in legs)
        tiers = client.risk_limit_tiers('linear', symbol)
        tier = next((t for t in tiers if need <= t['limit']), tiers[-1])
        for idx in (1, 2):        # both hedge indexes, always
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
        snapshot=None, snapshot_every=60, lock_path=None, allow_mainnet=False):
    load_env()
    notifier = make_notifier()
    # L1: build_fleet issues account writes (hedge mode, leverage, tiers) —
    # a second launch must die BEFORE those, so a coarse per-file lock comes
    # first; the per-account lock follows once the venues are known
    # H4: /tmp is age-cleaned by systemd-tmpfiles (default 10d) — a held
    # flock does not protect the FILE, so a long-running fleet silently
    # loses its lock. Locks live beside the logs the fleet already owns.
    lockdir = Path('logs')
    lockdir.mkdir(parents=True, exist_ok=True)
    prelock = acquire_fleet_lock(
        str(lockdir / f'{Path(fleet_path).resolve().name}.prelock'))
    fleet, clients, bots = build_fleet(fleet_path, notifier,
                                       allow_mainnet=allow_mainnet)
    lock_tag = '+'.join(f'{v}.{c.env}' for v, c in sorted(clients.items()))
    lock = acquire_fleet_lock(lock_path
                              or str(lockdir / f'{lock_tag}.lock'))
    try:
        notifier.ship_orders = (fleet['notify_orders'] if ship_orders is None
                                else ship_orders)
        poll = poll_seconds or fleet['poll_seconds']
        n = 0
        failing = 0
        lost_warn_t = 0.0
        while cycles is None or n < cycles:
            try:
                wallets = {v: c.read_wallet() for v, c in clients.items()}  # E8
                known = [w['equity'] for w in wallets.values()
                         if w['equity'] is not None]
                wallet = {'equity': sum(known) if known else None,
                          'mm_rate': max((w['mm_rate'] or 0.0)
                                         for w in wallets.values())}
                for bot in bots:
                    try:
                        counts = bot.cycle(
                            equity=wallets[bot.cfg['venue']]['equity'])
                    except Exception as e:              # noqa: BLE001
                        # M3: one bot's venue trouble must never starve the
                        # REST of the fleet's stop evaluation.
                        notifier.event('net', bot.botid,
                                       f'cycle lost: {type(e).__name__}: {e}')
                        continue
                    if counts is not None:
                        print(f"cycle {n} {bot.botid}: {counts}", flush=True)
                if snapshot and n % snapshot_every == 0:
                    row = snapshot_row(bots, wallet, time.time())
                    with open(snapshot, 'a') as f:
                        f.write(json.dumps(row) + '\n')
            except Exception as e:                       # noqa: BLE001
                # E7 at the loop: a failed read, a malformed venue response
                # (truncated JSON, an LB error page — the audit's M4), or an
                # ambiguous write — any costs THIS CYCLE, never the process.
                # No snapshot is written, so a persistent problem still
                # raises the watchdog's staleness page.
                failing += 1
                if time.time() - lost_warn_t >= 300.0:   # one page per 5 min,
                    lost_warn_t = time.time()            # not one per loss
                    import traceback
                    traceback.print_exc()
                    notifier.event('net', 'fleet',
                                   f'cycle {n} lost ({failing} in a row): '
                                   f'{type(e).__name__}: {e}')
            else:
                if failing:
                    notifier.event('net', 'fleet',
                                   f'venue readable again after {failing} '
                                   'lost cycle(s)')
                failing = 0
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
        prelock.close()
