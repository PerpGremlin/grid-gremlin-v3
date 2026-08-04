# The lattice, the lot, and the split (SPEC G1-G6, B8; E1 pure throughout).
#
# This is the one ladder module (MIGRATION #6): the martingale runs these same
# functions with different data at slice 5. Everything here is a pure function
# of its arguments — no I/O, no clock, no module state (E1), and the lattice is
# a function of config alone: price never moves it (G1, E4).

import math
from decimal import Decimal

FEE_FLOOR_PCT = 0.001    # G6: an exit must clear costs; a constant, not a knob
CROSS_GUARD_BPS = 5.0    # B3/B8: one definition; the placer imports THIS one
SPACING_GUARD_MULTIPLE = 3.0   # B8: spacing must clear the guard with margin


def grid_rungs(cfg, adapter):
    """G1: N tick-rounded prices spanning [lower, upper] inclusive, computed
    once from config. G3: N rungs, N-1 gaps — the divisor is load-bearing."""
    lower, upper, n = cfg['lower'], cfg['upper'], cfg['rungs']
    if cfg['spacing_type'] == 'percent':
        ratio = (upper / lower) ** (1.0 / (n - 1))
        prices = [lower * ratio ** i for i in range(n)]
    else:
        step = (upper - lower) / (n - 1)
        prices = [lower + step * i for i in range(n)]
    prices[-1] = upper                       # endpoints exact before rounding
    return [adapter.round_price(p) for p in prices]


def rung_notionals(cfg):
    """The quote slice each rung is allotted: ladder_notional x w_i/sum(w)."""
    n, total = cfg['rungs'], cfg['ladder_notional']
    weights = cfg.get('rung_weights')
    if not weights:
        return [total / n] * n
    s = sum(weights)
    return [total * w / s for w in weights]


def lot(cfg, adapter, split_ref):
    """G4 (D5): THE canonical inventory unit — the mean rung notional priced at
    the split ref, floored to the venue's qty step. One anchor, every state."""
    notionals = rung_notionals(cfg)
    mean = sum(notionals) / len(notionals)
    return adapter.round_qty(adapter.qty_from_notional(mean, split_ref))


def exit_floor(side, split_ref, basis):
    """G6: the price an exit must clear — the basis-protected floor. The grid
    never sells below cost plus fees; with no basis, the ref alone rules."""
    if basis is None or basis <= 0:
        return split_ref
    if side == 'long':
        return max(split_ref, basis * (1.0 + FEE_FLOOR_PCT))
    return min(split_ref, basis * (1.0 - FEE_FLOOR_PCT))


def split(side, rungs, split_ref, basis=None):
    """G5: classify every rung — entries strictly on the entry side of the
    split ref, exit candidates strictly beyond the floor, both sorted
    nearest-the-money first. Rungs between ref and floor hold NOTHING — that
    empty zone is the un-configured no-trade band (D6), and on the ref itself
    a rung holds nothing either (the boundary belongs to neither side).

    Returns {'entries': [(i, price), ...], 'exits': [(i, price), ...]} where i
    is the lattice index (0 = lowest price, G1's convention)."""
    floor = exit_floor(side, split_ref, basis)
    indexed = list(enumerate(rungs))
    if side == 'long':
        entries = [(i, p) for i, p in indexed if p < split_ref]
        exits = [(i, p) for i, p in indexed if p > floor]
        entries.sort(key=lambda ip: -ip[1])      # nearest below ref first
        exits.sort(key=lambda ip: ip[1])         # nearest above floor first
    else:
        entries = [(i, p) for i, p in indexed if p > split_ref]
        exits = [(i, p) for i, p in indexed if p < floor]
        entries.sort(key=lambda ip: ip[1])
        exits.sort(key=lambda ip: -ip[1])
    return {'entries': entries, 'exits': exits}


def guard_band(bid, ask):
    """B3's band, defined once: max(spread, guard-bps of mid)."""
    return max(ask - bid, (bid + ask) / 2.0 * CROSS_GUARD_BPS / 1e4)


def min_gap(rungs):
    """The TRUE tightest gap — on a geometric lattice it is at the low end;
    v2's startup warning used the mean and lied on every geometric grid."""
    return min(b - a for a, b in zip(rungs, rungs[1:]))


def spacing_clears_guard(rungs, bid, ask):
    """B8: spacing must clear the guard band with stated margin, measured
    against the true minimum gap. Returns (ok, gap, guard) so the caller can
    put the numbers in the warning."""
    gap, guard = min_gap(rungs), guard_band(bid, ask)
    return gap >= SPACING_GUARD_MULTIPLE * guard, gap, guard


# --- the plan level: caps, the exit ladder, the entry guard (G7-G13) ---------

UNBOUNDED = 'unbounded'


def sellable_base(cfg, adapter, held_base):
    """G9: what the exit ladder may cover — held minus the floor. NEVER the
    same variable as held: conflating them once made a live ceiling cap+floor."""
    return adapter.round_qty(max(0.0, abs(held_base) - cfg['min_position_base']))


def position_cap(cfg, adapter, rungs):
    """G10: the ceiling in base units. 'unbounded' -> None; absent -> the full
    ladder (the position if every rung filled once)."""
    cap = cfg.get('max_position_base')
    if cap == UNBOUNDED:
        return None
    if cap is not None:
        return float(cap)
    notionals = rung_notionals(cfg)
    return sum(adapter.qty_from_notional(nt, p) for nt, p in zip(notionals, rungs))


def lots_free(cap, held_base, lot_qty):
    """G10: whole lots of headroom under the cap, measured against HELD."""
    if cap is None or lot_qty <= 0:
        return None                                # unbounded
    return max(0, int((cap - abs(held_base)) / lot_qty + 1e-9))


def lots_held(sellable, lot_qty):
    """G7's count: lots believed armed-and-filled, measured against SELLABLE —
    grid inventory only, so a floored stack cannot suppress the entry ladder."""
    if lot_qty <= 0:
        return 0
    return int(round(sellable / lot_qty))


def exit_ladder(exits, sellable, lot_qty, adapter):
    """G8: pour the sellable inventory one lot per eligible exit rung,
    nearest-first; the last rung absorbs a 0.5-1.5 lot remainder rather than
    minting a sub-lot dust rung; a share below the venue minimum walks outward
    to the first placeable rung (long exits get cheaper to place going up, so
    inventory is never silently dropped). Returns [(i, price, qty)].

    The pour runs in INTEGER qty-steps: float subtraction plus flooring eats a
    step per iteration — measured while writing this function's own spec."""
    step = adapter.qty_step
    if sellable <= 0 or not exits or lot_qty <= 0 or step <= 0:
        return []
    total = int(round(sellable / step))
    lot_steps = max(1, int(round(lot_qty / step)))
    if total <= 0:
        return []

    def qty(steps):
        return float(Decimal(str(step)) * steps)

    kept, remaining = [], total
    for n, (i, price) in enumerate(exits):
        if remaining <= 0:
            break
        dump = remaining * 2 <= lot_steps * 3 or n == len(exits) - 1
        share = remaining if dump else lot_steps
        if adapter.meets_minimum(qty(share), price):
            kept.append([i, price, share])
        elif kept:
            kept[-1][2] += share
        else:
            continue        # sub-minimum with nothing kept yet: walk outward
        remaining -= share
        if dump:
            break
    if remaining > 0 and kept:
        kept[-1][2] += remaining
    return [(i, price, qty(s)) for i, price, s in kept]


def plan_grid(cfg, adapter, split_ref, held_base=0.0, basis=None):
    """G12: the netted plan — a pure function of (config, ref, position,
    basis). Entries below the ref beyond the suppressed prefix (G7), exits
    covering the sellable inventory beyond the basis floor (G5/G6/G8), the cap
    bounding accumulation (G10). No order it emits is marketable (G13's
    plan-level half): entries only on the entry side of the ref, exits only
    beyond the floor — both inherited from split().

    Returns order dicts: {rung, side, price, qty, reduce_only}."""
    rungs = grid_rungs(cfg, adapter)
    parts = split(cfg['side'], rungs, split_ref, basis)
    lot_qty = lot(cfg, adapter, split_ref)
    sellable = sellable_base(cfg, adapter, held_base)
    notionals = rung_notionals(cfg)

    entry_side, exit_side = ('Buy', 'Sell') if cfg['side'] == 'long' else ('Sell', 'Buy')
    exits_ro = cfg['market_type'] != 'spot'
    orders = []

    for i, price, qty in exit_ladder(parts['exits'], sellable, lot_qty, adapter):
        orders.append({'rung': i, 'side': exit_side, 'price': price, 'qty': qty,
                       'reduce_only': exits_ro})

    free = lots_free(position_cap(cfg, adapter, rungs), held_base, lot_qty)
    suppressed = lots_held(sellable, lot_qty)      # G7: the arming-order prefix
    for i, price in parts['entries'][suppressed:]:
        if free is not None and free <= 0:
            break
        qty = adapter.round_qty(adapter.qty_from_notional(notionals[i], price))
        if qty <= 0 or not adapter.meets_minimum(qty, price):
            continue
        orders.append({'rung': i, 'side': entry_side, 'price': price, 'qty': qty,
                       'reduce_only': False})
        if free is not None:
            free -= 1
    return orders
