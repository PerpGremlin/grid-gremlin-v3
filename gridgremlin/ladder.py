# The lattice, the lot, and the split (SPEC G1-G6, B8; E1 pure throughout).
#
# This is the one ladder module (MIGRATION #6): the martingale runs these same
# functions with different data at slice 5. Everything here is a pure function
# of its arguments — no I/O, no clock, no module state (E1), and the lattice is
# a function of config alone: price never moves it (G1, E4).

import math

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
