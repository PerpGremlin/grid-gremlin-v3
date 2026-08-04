# The ladder: lattice, lot, split, exits, caps (SPEC G1-G13). Pure (E1).
# The why lives in docs/SPEC.md — code cites IDs and states only what the
# code itself cannot show.

import math
from decimal import Decimal

FEE_FLOOR_PCT = 0.001    # G6: an exit must clear costs; a constant, not a knob
CROSS_GUARD_BPS = 5.0    # B3/B8: one definition; the placer imports THIS one
SPACING_GUARD_MULTIPLE = 3.0   # B8: spacing must clear the guard with margin


def grid_rungs(cfg, adapter):
    """G1/G3: N tick-rounded prices over [lower, upper], N-1 gaps."""
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
    """Per-rung quote allocation: ladder_notional x w_i/sum(w)."""
    n, total = cfg['rungs'], cfg['ladder_notional']
    weights = cfg.get('rung_weights')
    if not weights:
        return [total / n] * n
    s = sum(weights)
    return [total * w / s for w in weights]


def lot(cfg, adapter, split_ref):
    """G4: the canonical lot — mean rung notional at the split ref."""
    notionals = rung_notionals(cfg)
    mean = sum(notionals) / len(notionals)
    return adapter.round_qty(adapter.qty_from_notional(mean, split_ref))


def exit_floor(side, split_ref, basis):
    """G6: the price an exit must clear; no basis -> the ref alone."""
    if basis is None or basis <= 0:
        return split_ref
    if side == 'long':
        return max(split_ref, basis * (1.0 + FEE_FLOOR_PCT))
    return min(split_ref, basis * (1.0 - FEE_FLOOR_PCT))


def split(side, rungs, split_ref, basis=None):
    """G5: entries strictly one side of the ref, exits strictly beyond the
    floor, nearest-first. Index 0 = lowest rung."""
    floor = exit_floor(side, split_ref, basis)
    indexed = list(enumerate(rungs))
    if side == 'long':
        entries = [(i, p) for i, p in indexed if p < split_ref]
        exits = [(i, p) for i, p in indexed if p > floor]
        entries.sort(key=lambda ip: -ip[1])
        exits.sort(key=lambda ip: ip[1])
    else:
        entries = [(i, p) for i, p in indexed if p > split_ref]
        exits = [(i, p) for i, p in indexed if p < floor]
        entries.sort(key=lambda ip: ip[1])
        exits.sort(key=lambda ip: -ip[1])
    return {'entries': entries, 'exits': exits}


def guard_band(bid, ask):
    """B3: max(spread, guard-bps of mid). Defined once."""
    return max(ask - bid, (bid + ask) / 2.0 * CROSS_GUARD_BPS / 1e4)


def min_gap(rungs):
    """B8: the true tightest gap (the mean lies on geometric grids)."""
    return min(b - a for a, b in zip(rungs, rungs[1:]))


def spacing_clears_guard(rungs, bid, ask):
    """B8: (ok, gap, guard) — gap measured at the true minimum."""
    gap, guard = min_gap(rungs), guard_band(bid, ask)
    return gap >= SPACING_GUARD_MULTIPLE * guard, gap, guard


# --- the plan level: caps, the exit ladder, the entry guard (G7-G13) ---------

UNBOUNDED = 'unbounded'


def sellable_base(cfg, adapter, held_base):
    """G9: held minus the floor — never the same variable as held."""
    return adapter.round_qty(max(0.0, abs(held_base) - cfg['min_position_base']))


def position_cap(cfg, adapter, rungs):
    """G10: 'unbounded' -> None; absent -> the full-ladder sum."""
    cap = cfg.get('max_position_base')
    if cap == UNBOUNDED:
        return None
    if cap is not None:
        return float(cap)
    notionals = rung_notionals(cfg)
    return sum(adapter.qty_from_notional(nt, p) for nt, p in zip(notionals, rungs))


def lots_free(cap, held_base, lot_qty):
    """G10: whole lots of headroom under the cap, measured off HELD."""
    if cap is None or lot_qty <= 0:
        return None                                # unbounded
    return max(0, int((cap - abs(held_base)) / lot_qty + 1e-9))


def lots_held(sellable, lot_qty):
    """G7: the suppression count, measured off SELLABLE."""
    if lot_qty <= 0:
        return 0
    return int(round(sellable / lot_qty))


def exit_ladder(exits, sellable, lot_qty, adapter):
    """G8: one lot per rung nearest-first; the last rung absorbs a 0.5-1.5
    lot remainder; sub-minimum shares walk outward. Integer qty-steps: float
    subtraction plus flooring loses a step per iteration."""
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
            continue
        remaining -= share
        if dump:
            break
    if remaining > 0 and kept:
        kept[-1][2] += remaining
    return [(i, price, qty(s)) for i, price, s in kept]


def plan_grid(cfg, adapter, split_ref, held_base=0.0, basis=None):
    """G12: the netted plan, pure. G7 suppression, G8 exits, G10 cap, G13
    non-marketable by construction. Returns {rung, side, price, qty,
    reduce_only} dicts."""
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
    suppressed = lots_held(sellable, lot_qty)
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


# --- the martingale: the same maths, different data (M1, M2, M8) -------------

def martingale_schedule(cfg):
    """M2: [(notional, cumulative deviation)] — index 0 is the base order."""
    k = cfg['order_size_multiplier']
    s = cfg['deviation_step_multiplier']
    d = cfg['deviation_pct']
    out = [(cfg['base_order_size'], 0.0)]
    cumdev = 0.0
    for i in range(cfg['max_averaging_orders']):
        cumdev += d * s ** i
        out.append((cfg['safety_order_size'] * k ** i, cumdev))
    return out


def plan_martingale(cfg, adapter, base_price, split_ref, held_base=0.0):
    """M1: safety orders from the schedule — cumulative-prefix suppression,
    entry side only (G13), no exits (the round TP is slice 12). The base order
    itself is lifecycle, not a resting rung."""
    sign = -1.0 if cfg['side'] == 'long' else 1.0
    entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'
    orders, cum = [], 0.0
    for n, (notional, cumdev) in enumerate(martingale_schedule(cfg)):
        price = adapter.round_price(base_price * (1.0 + sign * cumdev))
        qty = adapter.round_qty(adapter.qty_from_notional(notional, price))
        cum += qty
        if n == 0:
            continue
        if held_base >= cum - 1e-12:
            continue
        if (cfg['side'] == 'long') == (price >= split_ref):
            continue
        if qty <= 0 or not adapter.meets_minimum(qty, price):
            continue
        orders.append({'rung': n, 'side': entry_side, 'price': price,
                       'qty': qty, 'reduce_only': False})
    return orders
