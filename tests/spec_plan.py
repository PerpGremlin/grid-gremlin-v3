# Specs for SPEC G7-G13's plan-level half. The start-matrix rows for flat and
# simple-adopt, plus the sabotage specs (T1): G7, G9 and G13 are proven able
# to FAIL, not just observed passing.

from gridgremlin.adapters import LinearAdapter, SpotAdapter
from gridgremlin.config import validate_config
from gridgremlin.ladder import (grid_rungs, lot, split, exit_ladder,
                                sellable_base, position_cap, lots_free,
                                lots_held, plan_grid)

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
REF = 60000.0
LOT = 0.007          # mean 476.19 quote at 60,000, floored to 0.001


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


def _buys(orders):
    return sorted((o['price'] for o in orders if o['side'] == 'Buy'), reverse=True)


def _sells(orders):
    return sorted(o['price'] for o in orders if o['side'] == 'Sell')


# --- the start matrix: flat --------------------------------------------------

def spec_G12_flat_long_is_all_entries_no_exits():
    orders = plan_grid(_cfg(), ADAPTER, REF)
    assert _sells(orders) == []
    assert _buys(orders) == [50000.0 + 1000.0 * i for i in range(10)][::-1]
    assert all(not o['reduce_only'] for o in orders)


def spec_G13_flat_emits_nothing_marketable():
    orders = plan_grid(_cfg(), ADAPTER, REF)
    assert all(o['price'] < REF for o in orders if o['side'] == 'Buy')
    assert all(o['price'] > REF for o in orders if o['side'] == 'Sell')


# --- the start matrix: simple adopt, in profit -------------------------------

def spec_G8_adopt_in_profit_exits_one_lot_nearest_first():
    orders = plan_grid(_cfg(), ADAPTER, REF, held_base=3 * LOT, basis=55000.0)
    sells = [(o['price'], o['qty']) for o in orders if o['side'] == 'Sell']
    assert sorted(sells) == [(61000.0, LOT), (62000.0, LOT), (63000.0, LOT)]
    assert all(o['reduce_only'] for o in orders if o['side'] == 'Sell')


def spec_G7_adopted_lots_suppress_the_nearest_entries():
    orders = plan_grid(_cfg(), ADAPTER, REF, held_base=3 * LOT, basis=55000.0)
    buys = _buys(orders)
    assert buys[0] == 56000.0            # 59k, 58k, 57k suppressed (3 lots held)
    assert 59000.0 not in buys and 58000.0 not in buys and 57000.0 not in buys


def spec_G7_release_is_furthest_first_as_exits_fill():
    # one exit fills -> held shrinks one lot -> the FURTHEST suppressed entry
    # (57k) returns first, converging on the basis — the owner's dissolution,
    # mechanically (D6).
    after = plan_grid(_cfg(), ADAPTER, REF, held_base=2 * LOT, basis=55000.0)
    buys = _buys(after)
    assert buys[0] == 57000.0
    assert 59000.0 not in buys and 58000.0 not in buys


# --- the start matrix: simple adopt, underwater (G13's headline case) --------

def spec_G13_underwater_adopt_emits_nothing_between_mark_and_basis():
    orders = plan_grid(_cfg(), ADAPTER, REF, held_base=3 * LOT, basis=65000.0)
    floor = 65000.0 * 1.001
    assert _sells(orders)[0] == 66000.0             # first exit clears the basis
    assert all(p > floor for p in _sells(orders))   # no sell at a loss (G6)
    assert all(p < REF for p in _buys(orders))      # no buy above the mark
    zone = [o for o in orders if REF <= o['price'] <= floor]
    assert zone == []                               # the dead zone is EMPTY


# --- the start matrix: over-cap and floored adopts ---------------------------

def spec_G10_over_cap_adopt_arms_no_entries_but_still_covers():
    cfg = _cfg()
    cap = position_cap(cfg, ADAPTER, grid_rungs(cfg, ADAPTER))   # ~0.168
    orders = plan_grid(cfg, ADAPTER, REF, held_base=cap + 5 * LOT, basis=55000.0)
    assert _buys(orders) == []                       # zero headroom, G10
    covered = sum(o['qty'] for o in orders if o['side'] == 'Sell')
    assert abs(covered - ADAPTER.round_qty(cap + 5 * LOT)) < 1e-9


def spec_G9_the_floor_core_is_never_offered_and_never_suppresses():
    cfg = _cfg(min_position_base=2 * LOT)
    held = 5 * LOT                                   # stack: 2 floored + 3 grid
    orders = plan_grid(cfg, ADAPTER, REF, held_base=held, basis=55000.0)
    covered = sum(o['qty'] for o in orders if o['side'] == 'Sell')
    assert abs(covered - 3 * LOT) < 1e-9             # sellable only, not held
    assert _buys(orders)[0] == 56000.0               # suppression counts 3, not 5


def spec_G8_remainder_folds_never_a_dust_rung():
    # 3.4 lots: pour 1, 1, then 1.4 <= 1.5 lots dumps on the third rung
    sell = ADAPTER.round_qty(3.4 * LOT)              # 0.023
    exits = split('long', grid_rungs(_cfg(), ADAPTER), REF)['exits']
    ladder = exit_ladder(exits, sell, LOT, ADAPTER)
    assert [q for _, _, q in ladder] == [0.007, 0.007, 0.009]
    assert abs(sum(q for _, _, q in ladder) - sell) < 1e-9


def spec_G8_sub_minimum_shares_walk_outward_and_coverage_survives():
    fussy = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                           'price_tick': 0.1, 'min_qty': 0.001,
                           'min_notional': 400.0, 'settle_coin': 'USDT'})
    exits = split('long', grid_rungs(_cfg(), ADAPTER), REF)['exits']
    # a 0.006 lot is 366-396 quote at 61-66k — under the 400 minimum. The pour
    # must WALK OUTWARD to the first placeable rung (67k), never silently drop
    # the inventory (the draft bug this spec was written against).
    ladder = exit_ladder(exits, 0.018, 0.006, fussy)
    assert ladder[0][1] == 67000.0
    assert abs(sum(q for _, _, q in ladder) - 0.018) < 1e-9


# --- sabotage (T1): the guards are load-bearing, not decorative --------------

def spec_G7_sabotage_removing_suppression_rearms_a_held_rung():
    cfg = _cfg()
    parts = split('long', grid_rungs(cfg, ADAPTER), REF, basis=55000.0)
    unsuppressed = [p for _, p in parts['entries']]  # suppression bypassed
    assert 59000.0 in unsuppressed                   # the held rung re-arms ->
    correct = _buys(plan_grid(cfg, ADAPTER, REF, held_base=3 * LOT, basis=55000.0))
    assert 59000.0 not in correct                    # -> only G7 prevents stacking


def spec_G9_sabotage_conflating_held_and_sellable_inflates_headroom():
    cfg = _cfg(min_position_base=2 * LOT, max_position_base=6 * LOT)
    held, sell = 5 * LOT, sellable_base(cfg, ADAPTER, 5 * LOT)
    cap = position_cap(cfg, ADAPTER, grid_rungs(cfg, ADAPTER))
    assert lots_free(cap, sell, LOT) > lots_free(cap, held, LOT)
    # the overnight cap failure: measuring headroom off sellable raises the
    # effective ceiling to cap+floor. Two names, or a repeat of 2026-07-31.


def spec_G13_sabotage_bypassing_the_split_emits_marketable_sells():
    rungs = grid_rungs(_cfg(), ADAPTER)
    below_ref = [(i, p) for i, p in enumerate(rungs) if p < REF]  # split bypassed
    ladder = exit_ladder(below_ref, 3 * LOT, LOT, ADAPTER)
    assert ladder and all(p < REF for _, p, _ in ladder)
    # these WOULD be instant taker fills — the exact scenario the owner feared;
    # split() is the plan-level guard, and slices 9's placer + post-only are the
    # independent backstops (G13's other half).


def spec_G7_lots_held_counts_sellable_not_held():
    assert lots_held(3 * LOT, LOT) == 3
    assert lots_held(0.0, LOT) == 0                  # a fully-floored stack
    assert lots_held(3 * LOT, 0.0) == 0              # degenerate lot -> no guess


# --- spot: exits carry no reduce_only flag -----------------------------------

def spec_G12_spot_exits_are_plain_sells():
    spot = SpotAdapter({'symbol': 'ETHUSDT', 'qty_step': 0.0001,
                        'price_tick': 0.01, 'min_qty': 0.0001,
                        'min_notional': 1.0, 'settle_coin': 'USDT'})
    cfg = _cfg(market_type='spot', leverage=None, lower=1500.0, upper=2500.0,
               rungs=21, assumed_avg_entry=1800.0)
    orders = plan_grid(cfg, spot, 2000.0, held_base=0.05, basis=1800.0)
    sells = [o for o in orders if o['side'] == 'Sell']
    assert sells and all(o['reduce_only'] is False for o in sells)
