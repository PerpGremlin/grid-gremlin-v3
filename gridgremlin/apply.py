# Identity and the diff (SPEC I1-I3, E2's decision half). Pure.

from .config import ConfigError

PRICE_EPS = 1e-9
QTY_RTOL = 0.05


def make_botid(market_type, symbol, side):
    """I1: {market_type[:3]}{symbol}{side initial}, hyphens stripped (D20)."""
    return f'{market_type[:3]}{symbol}{side[0]}'.replace('-', '')


def make_link(botid, rung, gen):
    return f'{botid}-{rung}-{gen}'


def rung_of(link_id, botid):
    """I1: ours iff prefixed and the rung parses; anything else is None."""
    prefix = botid + '-'
    if not (link_id or '').startswith(prefix):
        return None
    tail = link_id[len(prefix):].split('-', 1)[0]
    try:
        return int(tail)
    except ValueError:
        return None


def check_link_fits(botid, max_rung, venue_limit, gen_chars=10):
    """I3: refuse at build, never skip a row silently."""
    longest = len(make_link(botid, max_rung, '9' * gen_chars))
    if longest > venue_limit:
        raise ConfigError(f'{botid}: order link would be {longest} chars '
                          f'(venue limit {venue_limit}) — shorten the symbol '
                          'set or the rung count')


def bot_identity(cfg, adapter):
    """I2: the collision key — (market_type, symbol, opening positionIdx)."""
    entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'
    idx = adapter.position_idx(entry_side, False)
    return (cfg['market_type'], cfg['symbol'], 0 if idx is None else idx)


def check_fleet_unique(identities):
    seen = {}
    for botid, ident in identities:
        if ident in seen:
            raise ConfigError(f'{botid} and {seen[ident]} both own {ident} — '
                              'one bot per (market_type, symbol, positionIdx)')
        seen[ident] = botid
    return identities


def matches(desired, order, qty_rtol=QTY_RTOL):
    """Truncation-tolerant: a venue-shrunk exit is a match; oversized is not."""
    if order['side'] != desired['side']:
        return False
    if bool(order['reduce_only']) != bool(desired['reduce_only']):
        return False
    if abs(order['price'] - desired['price']) > PRICE_EPS:
        return False
    dq, oq = desired['qty'], order['qty']
    if desired['reduce_only']:
        # truncation-tolerant DOWN TO A POINT: the venue shrinks an exit to
        # the position, but a resting order far below the desire is not
        # truncation, it is a grown position with a stale cover — matching
        # it forever left the growth unexited (audit 2026-08-07 MED). Below
        # three quarters, replace (the diff makes it an amend).
        return dq * 0.75 <= oq <= dq * (1.0 + qty_rtol)
    return abs(dq - oq) <= qty_rtol * dq


def diff(desired, resting, botid, qty_rtol=QTY_RTOL):
    """E2's decisions: keep matches, cancel our deviations, create the missing.
    Foreign orders are invisible (I1). Duplicates on one rung keep one match.
    Returns (to_cancel, to_create)."""
    ours = {}
    for o in resting:
        rung = rung_of(o.get('link_id'), botid)
        if rung is not None:
            ours.setdefault(rung, []).append(o)
    to_cancel, to_create = [], []
    for d in desired:
        candidates = ours.pop(d['rung'], [])
        kept = False
        for o in candidates:
            if not kept and matches(d, o, qty_rtol):
                kept = True
            else:
                to_cancel.append(o)
        if not kept:
            to_create.append(d)
    for leftovers in ours.values():
        to_cancel.extend(leftovers)              # rungs the plan no longer wants
    return to_cancel, to_create


def pair_amends(to_cancel, to_create, botid):
    """Same (rung, side, reduce_only) at the SAME price -> a qty-only amend.
    A moved price is never amended (the trail-shaped 3.8 lesson).
    Returns (amends, cancels, creates); amends are (order, desired) pairs."""
    def key(rung, item):
        return (rung, item['side'], bool(item['reduce_only']))

    creates_by_key = {}
    for d in to_create:
        creates_by_key.setdefault(key(d['rung'], d), []).append(d)
    amends, cancels = [], []
    for o in to_cancel:
        rung = rung_of(o.get('link_id'), botid)
        bucket = creates_by_key.get(key(rung, o), [])
        paired = None
        for d in bucket:
            if abs(o['price'] - d['price']) <= PRICE_EPS:
                paired = d
                break
        if paired is None:
            cancels.append(o)
        else:
            bucket.remove(paired)
            amends.append((o, paired))
    creates = [d for bucket in creates_by_key.values() for d in bucket]
    return amends, cancels, creates
