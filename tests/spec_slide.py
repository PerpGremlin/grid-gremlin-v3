# Specs for SPEC G17-G20 (the slide, D28) and T6 (the backtester's window).
# The slide is a ratchet over an unchanged lattice: the window moves by whole
# rungs in the favourable direction only, never back, never past the clamp.

import math

from gridgremlin.adapters import LinearAdapter
from gridgremlin.backtest import backtest
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.ladder import (grid_rungs, lattice_index, lattice_price,
                                plan_grid, slide_offset, split)

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
SLIDE = {'trigger_rungs': 2, 'max_rungs': 100, 'confirm_seconds': 0}


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed',
           'slide': dict(SLIDE)}
    row.update(over)
    return validate_config(row)


def _bar(o, h, l, c):
    return {'o': o, 'h': h, 'l': l, 'c': c}


# --- G17: one lattice, many windows ------------------------------------------

def spec_G17_a_slid_window_shares_prices_with_home_on_the_overlap():
    for st in ('fixed', 'percent'):
        cfg = _cfg(spacing_type=st)
        home = grid_rungs(cfg, ADAPTER)
        slid = grid_rungs(cfg, ADAPTER, offset=5)
        assert slid[:16] == home[5:], st           # identical prices, same index
        assert slid[-1] > home[-1]                 # five new rungs above
        assert grid_rungs(cfg, ADAPTER, offset=-3)[3:] == home[:18]  # and below
    assert lattice_price(_cfg(), 20) == 70000.0    # endpoint exact, any window


def spec_G17_rung_ids_are_absolute_lattice_indices():
    cfg = _cfg()
    parts = split('long', grid_rungs(cfg, ADAPTER, 5), 62500.0, offset=5)
    ids = {i for i, _ in parts['entries']} | {i for i, _ in parts['exits']}
    assert min(ids) == 5 and max(ids) == 25
    orders = plan_grid(cfg, ADAPTER, 62500.0, offset=5)
    assert {o['rung'] for o in orders} <= set(range(5, 26))
    # the same absolute rung has the same price from either window
    by_home = {o['rung']: o['price'] for o in plan_grid(cfg, ADAPTER, 62500.0)}
    by_slid = {o['rung']: o['price'] for o in orders}
    for r in set(by_home) & set(by_slid):
        assert by_home[r] == by_slid[r], r


def spec_G17_lattice_index_inverts_lattice_price():
    for st in ('fixed', 'percent'):
        cfg = _cfg(spacing_type=st)
        for j in (-4, 0, 7, 20, 33):
            assert abs(lattice_index(cfg, lattice_price(cfg, j)) - j) < 1e-9


# --- G18: the trigger and the ratchet ----------------------------------------

def spec_G18_no_slide_until_the_ref_is_trigger_rungs_beyond_the_top():
    cfg = _cfg()                                   # top 70000, step 1000, K=2
    assert slide_offset(cfg, 0, 69000.0) == 0      # inside
    assert slide_offset(cfg, 0, 71999.0) == 0      # one rung past: not yet
    new = slide_offset(cfg, 0, 72000.0)            # exactly K rungs past
    assert new > 0
    # the ref lands at ref_position (0.5) of the new window
    rungs = grid_rungs(cfg, ADAPTER, new)
    assert rungs[0] <= 72000.0 <= rungs[-1]
    assert abs(lattice_index(cfg, 72000.0) - new - 10) < 1.0


def spec_G18_a_long_window_never_retreats():
    cfg = _cfg()
    up = slide_offset(cfg, 0, 80000.0)
    assert up > 0
    assert slide_offset(cfg, up, 50000.0) == up    # the crash does not slide it
    assert slide_offset(cfg, up, 20000.0) == up


def spec_G18_a_short_window_slides_down_only():
    cfg = _cfg(side='short')
    assert slide_offset(cfg, 0, 51000.0) == 0
    down = slide_offset(cfg, 0, 48000.0)           # K rungs below the bottom
    assert down < 0
    rungs = grid_rungs(cfg, ADAPTER, down)
    assert rungs[0] <= 48000.0 <= rungs[-1]
    assert slide_offset(cfg, down, 90000.0) == down  # the rally does not lift it


def spec_G18_ref_position_one_puts_the_whole_ladder_below_the_ref():
    cfg = _cfg(slide=dict(SLIDE, ref_position=1.0))
    new = slide_offset(cfg, 0, 75000.0)
    assert grid_rungs(cfg, ADAPTER, new)[-1] <= 75000.0
    assert all(o['side'] == 'Buy' for o in plan_grid(cfg, ADAPTER, 75000.0, offset=new))


def spec_G18_without_slide_the_offset_is_frozen():
    cfg = _cfg(slide=None)
    assert 'slide' not in cfg or not cfg['slide']
    assert slide_offset(cfg, 0, 1e9) == 0


# --- G19: the clamp ----------------------------------------------------------

def spec_G19_the_clamp_bounds_the_window_from_home():
    cfg = _cfg(slide=dict(SLIDE, max_rungs=3))
    assert slide_offset(cfg, 0, 1e6) == 3
    assert slide_offset(cfg, 3, 1e6) == 3
    assert slide_offset(_cfg(side='short', slide=dict(SLIDE, max_rungs=3)),
                        0, 1.0) == -3


# --- G20: inventory survives the slide ----------------------------------------

def spec_G20_held_lots_keep_their_exits_after_a_slide():
    cfg = _cfg()
    held, basis = 0.02, 68000.0                    # two lots bought near the top
    new = slide_offset(cfg, 0, 72500.0)
    orders = plan_grid(cfg, ADAPTER, 72500.0, held, basis, offset=new)
    exits = [o for o in orders if o['side'] == 'Sell']
    assert exits and abs(sum(o['qty'] for o in exits) - held) < 1e-9
    assert all(o['price'] >= basis * 1.001 for o in exits)      # G6 floor holds
    assert all(o['price'] > 72500.0 for o in exits)             # G13: not marketable


# --- the sabotage: without the slide a trend leaves the grid idle ------------

def _trend(start=60000.0, per_bar=600.0, bars=60):
    """A rising zig-zag: every bar dips 1.3 rungs and rallies 1.1 rungs, net
    +0.6 rungs — a grid inside its range trips every bar; outside, nothing."""
    out, p = [], start
    for _ in range(bars):
        out.append(_bar(p, p + 1100.0, p - 1300.0, p + per_bar))
        p += per_bar
    return out


def spec_G18_sabotage_no_slide_idles_through_a_trend():
    bars = _trend()
    frozen = backtest(_cfg(slide=None), ADAPTER, bars, fee_rate=0.0002)
    sliding = backtest(_cfg(), ADAPTER, bars, fee_rate=0.0002)
    assert frozen['slides'] == 0 and sliding['slides'] >= 2
    # the frozen grid stops trading once price leaves 70000; the slid one keeps going
    assert sliding['trips'] > frozen['trips'] * 2
    assert sliding['entry_fills'] > frozen['entry_fills'] * 2
    assert sliding['net'] > frozen['net']


# --- T6: the backtester rests only the window ---------------------------------

def spec_T6_a_rung_outside_the_window_never_fills():
    cfg = _cfg(slide=None, place_within_pct=0.02)   # 2%: 58800..61200 at 60000
    r = backtest(cfg, ADAPTER, [_bar(60000.0, 60100.0, 55500.0, 59500.0)])
    assert r['entry_fills'] == 1                     # 59000 rests; 56000-58000 do not
    wide = backtest(_cfg(slide=None, place_within_pct=0.2), ADAPTER,
                    [_bar(60000.0, 60100.0, 55500.0, 59500.0)])
    assert wide['entry_fills'] == 4


# --- C: the key is bounded ----------------------------------------------------

def spec_C3_slide_knobs_are_bounded_and_defaulted():
    cfg = _cfg()
    assert cfg['slide'] == {'trigger_rungs': 2, 'max_rungs': 100,
                            'ref_position': 0.5, 'confirm_seconds': 0.0}
    ok = {'trigger_rungs': 1, 'max_rungs': 5, 'confirm_seconds': 0}
    for bad in (dict(ok, trigger_rungs=0), {'trigger_rungs': 1},
                dict(ok, trigger_rungs=1.5), dict(ok, ref_position=1.5),
                dict(ok, snap_home=True), dict(ok, confirm_seconds=-1),
                {'trigger_rungs': 1, 'max_rungs': 5},      # G21: never defaulted
                'yes'):
        try:
            _cfg(slide=bad)
        except ConfigError:
            continue
        raise AssertionError(f'accepted {bad!r}')
    try:
        validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                         'side': 'long', 'strategy': 'martingale',
                         'capital': 100.0, 'leverage': 5, 'base_order_size': 10,
                         'safety_order_size': 10, 'order_size_multiplier': 1.5,
                         'deviation_pct': 0.01, 'deviation_step_multiplier': 1.0,
                         'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01,
                         'slide': dict(SLIDE)})
    except ConfigError as e:
        assert 'slide' in str(e)
    else:
        raise AssertionError('a martingale accepted slide')
