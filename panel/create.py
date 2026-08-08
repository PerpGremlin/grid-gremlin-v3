"""The create flow's gates (docs/DASHBOARD.md §11), pure and testable.

A proposal is one object: {'bot': {...}, 'watchdog': {'max': N}}. The
gates run in order — whole-fleet validation (the engine's own loaders,
coverage included), diff, keyless dry-run — and apply is an atomic file
write that ends at the file: enacting is phase 3's job.
"""
import difflib
import json
import os
import tempfile
from pathlib import Path

from gridgremlin.adapters import adapter_for
from gridgremlin.apply import make_botid
from gridgremlin.config import (ConfigError, validate_fleet)
from gridgremlin.ladder import grid_rungs, plan_grid, position_cap
from gridgremlin.main import check_watchdog_coverage
from gridgremlin.watchdog import validate_watchdog

CEILING_PREFILL = 1.2      # inside F2's [cap, 1.5x cap] band


def merge_proposal(fleet_raw, wd_raw, proposal):
    """Bot and watcher land together (§8: one act) — into COPIES."""
    bot = proposal['bot']
    botid = make_botid(bot['market_type'], bot['symbol'], bot['side'])
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw))
    if any(make_botid(b['market_type'], b['symbol'], b['side']) == botid
           for b in fleet.get('bots', [])):
        raise ConfigError(f'{botid}: already in this fleet — edit or '
                          'remove it first; identities are not reused')
    fleet.setdefault('bots', []).append(bot)
    wd.setdefault('positions', {})[botid] = {
        'min': 0, 'max': proposal['watchdog']['max']}
    return botid, fleet, wd


def edit_proposal(fleet_raw, wd_raw, botid, bot, wmax):
    """§11 for a changed bot: the entry and its watcher move together —
    identity is fixed (market, symbol, side never change in an edit;
    that is a remove plus a create, deliberately)."""
    new_id = make_botid(bot['market_type'], bot['symbol'], bot['side'])
    if new_id != botid:
        raise ConfigError(f'{botid}: an edit cannot change identity '
                          f'(-> {new_id}) — remove and create instead')
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw))
    for i, b in enumerate(fleet.get('bots', [])):
        if make_botid(b['market_type'], b['symbol'], b['side']) == botid:
            fleet['bots'][i] = bot
            wd.setdefault('positions', {})[botid] = {'min': 0, 'max': wmax}
            return botid, fleet, wd
    raise ConfigError(f'{botid}: not in this fleet')


def remove_proposal(fleet_raw, wd_raw, botid):
    """The bot and its watchdog line leave together — coverage would
    refuse an orphan in either direction (F1)."""
    fleet = json.loads(json.dumps(fleet_raw))
    wd = json.loads(json.dumps(wd_raw))
    before = len(fleet.get('bots', []))
    fleet['bots'] = [b for b in fleet.get('bots', [])
                     if make_botid(b['market_type'], b['symbol'],
                                   b['side']) != botid]
    if len(fleet['bots']) == before:
        raise ConfigError(f'{botid}: not in this fleet')
    (wd.get('positions') or {}).pop(botid, None)
    return botid, fleet, wd


def validate_whole(fleet, wd, adapter_of):
    """Gate 1: the engine's own loaders over the MERGED result — a new bot
    is judged as part of its fleet, never alone. Returns the refusal text
    verbatim, or None. adapter_of(cfg) is injected so specs need no
    network and the panel can use public endpoints."""
    try:
        vfleet = validate_fleet(fleet)
        vwd = validate_watchdog(wd)
        caps = []
        for cfg in vfleet['bots']:
            botid = make_botid(cfg['market_type'], cfg['symbol'],
                               cfg['side'])
            cap = None
            if cfg.get('strategy', 'grid') == 'grid':
                adapter = adapter_of(cfg)
                cap = position_cap(cfg, adapter, grid_rungs(cfg, adapter))
            caps.append((botid, cap))
        check_watchdog_coverage(caps, vwd)
    except ConfigError as e:
        return str(e)
    return None


def unified_diff(old_text, new_text, name):
    """Gate 2: the change as text — what review has always looked like."""
    return ''.join(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f'{name} (current)', tofile=f'{name} (proposed)'))


def dry_ladder(cfg, adapter, mark):
    """Gate 3: the orders the new bot would want at this mark — plan only,
    keyless, nothing placed."""
    return plan_grid(cfg, adapter, mark, 0.0, None, mark, mark)


def atomic_write(path, text):
    """Apply's only primitive: tempfile + os.replace, .bak kept. 'Safe'
    means an atomic rename, not an exception handler (the OctoBot
    safe_dump lesson, audit 2026-08-07 prior-art)."""
    p = Path(path)
    if p.exists():
        p.with_suffix(p.suffix + '.bak').write_text(p.read_text())
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except BaseException:
        os.unlink(tmp)
        raise


def public_adapter(cfg):
    """An adapter from PUBLIC endpoints — the panel holds no keys."""
    from gridgremlin.exchange.bybit.klines import fetch_instrument
    from gridgremlin.exchange.bybit.truth import parse_instrument
    return adapter_for(cfg['market_type'], parse_instrument(
        cfg['market_type'],
        fetch_instrument(cfg['market_type'], cfg['symbol'])))


def public_mark(cfg):
    import urllib.parse
    import urllib.request
    from gridgremlin.exchange.bybit.klines import PUBLIC_HOST
    q = urllib.parse.urlencode({'category': cfg['market_type'],
                                'symbol': cfg['symbol']})
    with urllib.request.urlopen(
            f'{PUBLIC_HOST}/v5/market/tickers?{q}', timeout=20) as r:
        row = json.load(r)['result']['list'][0]
    return float(row.get('markPrice') or row['lastPrice'])
