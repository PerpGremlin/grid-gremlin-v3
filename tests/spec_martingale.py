# Specs for SPEC M1, M2, M5's config half, M8. Golden fixtures from the field
# study (the 3Commas conventions, DECISIONS D11).

from gridgremlin.adapters import LinearAdapter
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.ladder import martingale_schedule, plan_martingale, plan_grid

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}
    row.update(over)
    return validate_config(row)


def _refused(row, *fragments):
    try:
        validate_config(row)
    except ConfigError as e:
        for frag in fragments:
            assert frag in str(e), f'expected {frag!r} in {str(e)!r}'
        return str(e)
    raise AssertionError(f'accepted, expected refusal: {fragments}')


# --- M2: the 3Commas schedule, golden ----------------------------------------

def spec_M2_size_progression_is_multiplier_of_previous():
    sched = martingale_schedule(_cfg())
    assert [n for n, _ in sched] == [1000.0, 1000.0, 2000.0, 4000.0]


def spec_M2_deviation_steps_compound():
    # the canonical 3Commas example: 1% deviation, step scale 2 -> -1%, -3%, -7%
    sched = martingale_schedule(_cfg())
    assert [round(d, 6) for _, d in sched] == [0.0, 0.01, 0.03, 0.07]


def spec_M2_flat_multipliers_give_equal_sizes_and_spacing():
    sched = martingale_schedule(_cfg(order_size_multiplier=1.0,
                                     deviation_step_multiplier=1.0))
    assert [n for n, _ in sched] == [1000.0] * 4
    assert [round(d, 6) for _, d in sched] == [0.0, 0.01, 0.02, 0.03]


def spec_M2_series_total_refusal_states_the_numbers():
    msg = _refused({'strategy': 'martingale', 'market_type': 'linear',
                    'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
                    'leverage': 10, 'base_order_size': 1000.0,
                    'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
                    'deviation_pct': 0.01, 'max_averaging_orders': 4,
                    'take_profit_avg_pct': 0.01},
                   '16000', '1600', 'capital is 1000')
    assert 'max_averaging_orders' in msg          # the message says what to lower


def spec_M2_vocabulary_bounds():
    _refused({**_row_dict(), 'order_size_multiplier': 0.5})   # < 1 shrinks: refused
    _refused({**_row_dict(), 'max_averaging_orders': 0})
    _refused({**_row_dict(), 'max_averaging_orders': 2.5})
    _refused({**_row_dict(), 'deviation_pct': 0})


def _row_dict():
    return {'strategy': 'martingale', 'market_type': 'linear',
            'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
            'leverage': 10, 'base_order_size': 100.0,
            'safety_order_size': 100.0, 'deviation_pct': 0.01,
            'max_averaging_orders': 3, 'take_profit_avg_pct': 0.01}


# --- M8: no range bounds -----------------------------------------------------

def spec_M8_range_bounds_are_not_martingale_keys():
    _refused({**_row_dict(), 'lower': 50000.0}, 'unknown key')
    _refused({**_row_dict(), 'upper': 70000.0}, 'unknown key')


def spec_M8_depth_derives_from_the_schedule():
    sched = martingale_schedule(_cfg())
    assert max(d for _, d in sched) == 0.07       # 7% deep at 3 orders, typed nowhere


# --- M5's config half --------------------------------------------------------

def spec_M5_repeat_is_a_coerced_flag():
    assert _cfg(repeat=1)['repeat'] is True
    assert _cfg()['repeat'] is False


def spec_M5_absolute_take_profit_stays_retired():
    _refused({**_row_dict(), 'take_profit_price': 60000.0}, 'retired')


# --- M1: the same maths, demonstrably ----------------------------------------

def spec_M1_flat_martingale_reproduces_the_grid_entry_ladder():
    # multiplier 1 + arithmetic deviations == a grid's entry ladder over the
    # same prices, through the same adapter maths — one implementation (M1).
    grid_cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                                'side': 'long', 'capital': 1000.0,
                                'leverage': 10, 'upper': 70000.0,
                                'lower': 50000.0, 'rungs': 21,
                                'spacing_type': 'fixed'})
    grid_buys = {(o['price'], o['qty'])
                 for o in plan_grid(grid_cfg, ADAPTER, 60000.0)}
    per_rung = 10000.0 / 21
    mart_cfg = _cfg(base_order_size=per_rung, safety_order_size=per_rung,
                    order_size_multiplier=1.0, deviation_pct=1.0 / 60.0,
                    deviation_step_multiplier=1.0, max_averaging_orders=9)
    mart_buys = {(o['price'], o['qty'])
                 for o in plan_martingale(mart_cfg, ADAPTER, 60000.0, 60000.0)}
    assert mart_buys and mart_buys <= grid_buys   # same prices, same qtys


def spec_M1_cumulative_prefix_suppression():
    cfg = _cfg()
    sched = martingale_schedule(cfg)
    base_qty = ADAPTER.round_qty(sched[0][0] / 60000.0)
    s1_qty = ADAPTER.round_qty(sched[1][0] / (60000.0 * 0.99))
    full = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0)
    assert [o['rung'] for o in full] == [1, 2, 3]
    held = plan_martingale(cfg, ADAPTER, 60000.0, 60000.0,
                           held_base=base_qty + s1_qty)
    assert [o['rung'] for o in held] == [2, 3]     # base + s1 filled -> s1 gone


def spec_G13_martingale_orders_stay_on_the_entry_side():
    # ref below the first safety order: that order would be a marketable buy
    cfg = _cfg()
    orders = plan_martingale(cfg, ADAPTER, 60000.0, 58500.0)
    prices = [o['price'] for o in orders]
    assert 59400.0 not in prices                   # s1 (-1%) skipped: >= ref
    assert prices and all(p < 58500.0 for p in prices)


def spec_C5_placeable_defers_for_martingale():
    from gridgremlin.config import check_placeable
    assert check_placeable(_cfg(), ADAPTER)        # no refusal without a price
