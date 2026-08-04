# Specs for SPEC G1-G6, B8, E1/E4's ladder half. Golden ladders hand-computed.

import math
from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.config import validate_config
from gridgremlin.ladder import (FEE_FLOOR_PCT, grid_rungs, rung_notionals, lot,
                                exit_floor, split, min_gap, guard_band,
                                spacing_clears_guard)

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


# --- G1/G3: the lattice ------------------------------------------------------

def spec_G1_arithmetic_lattice_golden():
    rungs = grid_rungs(_cfg(), ADAPTER)
    assert rungs == [50000.0 + 1000.0 * i for i in range(21)]  # step = range/(N-1)
    assert rungs[0] == 50000.0 and rungs[-1] == 70000.0        # endpoints exact


def spec_G1_geometric_lattice_golden():
    rungs = grid_rungs(_cfg(spacing_type='percent'), ADAPTER)
    ratio = (70000.0 / 50000.0) ** (1.0 / 20)                  # N-1 divisor (G3)
    for i, p in enumerate(rungs[:-1]):
        assert abs(p - round(50000.0 * ratio ** i, 1)) <= 0.05, (i, p)
    assert rungs[-1] == 70000.0
    assert all(b > a for a, b in zip(rungs, rungs[1:]))         # monotonic


def spec_G3_gap_count_is_rungs_minus_one():
    rungs = grid_rungs(_cfg(), ADAPTER)
    assert len(rungs) == 21 and len(list(zip(rungs, rungs[1:]))) == 20


def spec_E4_price_never_moves_the_lattice():
    # G1's E4 half: the lattice is a function of config alone; recomputing it
    # while "price" is anything at all yields the identical list.
    cfg = _cfg(spacing_type='percent')
    assert grid_rungs(cfg, ADAPTER) == grid_rungs(cfg, ADAPTER)
    # and split() reclassifies rungs but never re-prices them
    rungs = grid_rungs(cfg, ADAPTER)
    before = split('long', rungs, 60000.0)
    after = split('long', rungs, 64000.0)
    assert {p for _, p in before['entries'] + before['exits']} <= set(rungs)
    assert {p for _, p in after['entries'] + after['exits']} <= set(rungs)


# --- G4: the lot, one anchor -------------------------------------------------

def spec_G4_lot_is_mean_notional_at_the_split_ref():
    cfg = _cfg()                                   # 10,000 quote over 21 rungs
    assert lot(cfg, ADAPTER, 60000.0) == 0.007     # 476.19/60000 floored to step
    # one anchor in every state: the lot depends on ref and config, nothing else
    assert lot(cfg, ADAPTER, 60000.0) == lot(cfg, ADAPTER, 60000.0)
    assert lot(cfg, ADAPTER, 50000.0) == 0.009     # 476.19/50000 -> 0.00952 floored


def spec_G4_weighted_lot_uses_the_mean():
    cfg = _cfg(rung_sizing='weighted', rung_weights=[1.0] * 20 + [21.0])
    # mean of notionals is total/N regardless of shape — the weighted top rung
    # must not become the unit (v2's whole-stack-on-one-order lesson)
    assert lot(cfg, ADAPTER, 60000.0) == 0.007


# --- G5/G6: the split and the floor ------------------------------------------

def spec_G5_long_split_strict_sides_nearest_first():
    rungs = grid_rungs(_cfg(), ADAPTER)
    s = split('long', rungs, 60000.0)              # ref exactly on rung 10
    assert [p for _, p in s['entries']][:3] == [59000.0, 58000.0, 57000.0]
    assert [p for _, p in s['exits']][:3] == [61000.0, 62000.0, 63000.0]
    on_ref = {p for _, p in s['entries'] + s['exits']}
    assert 60000.0 not in on_ref                   # the boundary rung holds nothing


def spec_G5_short_split_mirrors():
    rungs = grid_rungs(_cfg(side='short'), ADAPTER)
    # short IN PROFIT (entered 62,000, mark 60,000): ref wins the floor —
    # exits (buy-backs) rest strictly below the ref, nearest first
    s = split('short', rungs, 60000.0, basis=62000.0)
    assert [p for _, p in s['entries']][:2] == [61000.0, 62000.0]
    assert exit_floor('short', 60000.0, 62000.0) == 60000.0
    assert [p for _, p in s['exits']][:3] == [59000.0, 58000.0, 57000.0]
    # short UNDERWATER (entered 55,000, mark 60,000): the basis wins — exits
    # only below 55,000 x 0.999, and the zone between floor and ref is empty
    u = split('short', rungs, 60000.0, basis=55000.0)
    floor = 55000.0 * (1.0 - FEE_FLOOR_PCT)        # 54,945
    assert all(p < floor for _, p in u['exits'])
    assert u['exits'][0][1] == 54000.0             # nearest below the floor
    zone = [p for p in rungs if floor <= p <= 60000.0]
    placed = {p for _, p in u['entries'] + u['exits']}
    assert zone and not (set(zone) & placed)       # the short's dead zone


def spec_G6_in_profit_the_ref_wins_the_floor():
    assert exit_floor('long', 60000.0, 55000.0) == 60000.0   # max(ref, 55055)
    rungs = grid_rungs(_cfg(), ADAPTER)
    s = split('long', rungs, 60000.0, basis=55000.0)
    assert all(p > 60000.0 for _, p in s['exits'])  # never a sell below ref


def spec_G6_underwater_the_basis_wins_and_the_dead_zone_is_empty():
    # long, mark 60,000, basis 65,000: the zone between them holds NOTHING —
    # the owner's deadband, emergent (D6); G13's plan-level shape.
    rungs = grid_rungs(_cfg(), ADAPTER)
    s = split('long', rungs, 60000.0, basis=65000.0)
    floor = 65000.0 * 1.001                        # 65,065
    assert all(p < 60000.0 for _, p in s['entries'])
    assert all(p > floor for _, p in s['exits'])
    zone = [p for p in rungs if 60000.0 <= p <= floor]
    placed = {p for _, p in s['entries'] + s['exits']}
    assert zone and not (set(zone) & placed)       # 60k..65k rungs: empty
    assert s['exits'][0][1] == 66000.0             # first exit clears the basis


def spec_G6_no_basis_means_the_ref_alone_rules():
    assert exit_floor('long', 60000.0, None) == 60000.0
    assert exit_floor('long', 60000.0, 0) == 60000.0


# --- B8: the guard check uses the TRUE minimum gap ---------------------------

def spec_B8_min_gap_is_the_tight_end_of_a_geometric_grid():
    rungs = grid_rungs(_cfg(spacing_type='percent'), ADAPTER)
    gaps = [b - a for a, b in zip(rungs, rungs[1:])]
    assert min_gap(rungs) == gaps[0]               # tightest at the low end
    assert min_gap(rungs) < sum(gaps) / len(gaps)  # the mean would lie (v2 bug)


def spec_B8_spacing_guard_fires_on_min_not_mean():
    rungs = grid_rungs(_cfg(spacing_type='percent'), ADAPTER)
    # choose a book whose guard sits between min gap/3 and mean gap/3:
    # min gap ~857, mean gap 1000 -> guard 300: 857 < 900 fails, 1000 >= 900 passes
    ok, gap, guard = spacing_clears_guard(rungs, 59850.0, 60150.0)
    assert guard == 300.0 and gap < 3.0 * guard and not ok
    arith = grid_rungs(_cfg(), ADAPTER)
    ok2, gap2, _ = spacing_clears_guard(arith, 59850.0, 60150.0)
    assert gap2 == 1000.0 and ok2                  # same book, arithmetic passes


def spec_B8_guard_band_is_spread_or_bps_whichever_larger():
    assert guard_band(59999.0, 60001.0) == 60000.0 * 5.0 / 1e4   # 30 > spread 2
    assert guard_band(59900.0, 60100.0) == 200.0                 # spread wins


# --- E1: purity, mechanically ------------------------------------------------

def spec_E1_ladder_module_is_pure():
    src = Path('gridgremlin/ladder.py').read_text()
    for banned in ('urllib', 'socket', 'http', 'requests', 'time.', 'datetime',
                   'random'):
        assert banned not in src, f'ladder.py must stay pure: found {banned!r}'
