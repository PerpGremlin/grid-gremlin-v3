# Specs for SPEC A1-A6. Golden fixtures, hand-computed.

from pathlib import Path

from gridgremlin.adapters import (InstrumentError, LinearAdapter, InverseAdapter,
                                  SpotAdapter, adapter_for)

SPEC_BTC_LINEAR = {'symbol': 'BTCUSDT', 'qty_step': 0.001, 'price_tick': 0.1,
                   'min_qty': 0.001, 'min_notional': 5.0, 'settle_coin': 'USDT'}
SPEC_BTC_INVERSE = {'symbol': 'BTCUSD', 'qty_step': 1, 'price_tick': 0.5,
                    'min_qty': 1, 'min_notional': None, 'settle_coin': 'BTC'}
SPEC_ETH_SPOT = {'symbol': 'ETHUSDT', 'qty_step': 0.00001, 'price_tick': 0.01,
                 'min_qty': 0.00001, 'min_notional': 1.0, 'settle_coin': 'USDT'}


def _refused(fn, *args):
    try:
        fn(*args)
    except InstrumentError:
        return
    raise AssertionError('expected InstrumentError')


# --- A1: built from a venue spec, refuse what cannot be traded ---------------

def spec_A1_missing_spec_fields_refuse():
    for absent in ('qty_step', 'price_tick', 'min_qty'):
        broken = dict(SPEC_BTC_LINEAR)
        broken[absent] = None
        _refused(LinearAdapter, broken)
    _refused(adapter_for, 'options', SPEC_BTC_LINEAR)


# --- A2: qty floors, price rounds; strings are exchange-ready ----------------

def spec_A2_qty_always_floors():
    a = LinearAdapter(SPEC_BTC_LINEAR)
    assert a.round_qty(0.0049) == 0.004          # never more than intended
    assert a.round_qty(0.0050) == 0.005
    assert a.fmt_qty(0.0049) == '0.004'


def spec_A2_price_rounds_half_up_to_tick():
    a = LinearAdapter(SPEC_BTC_LINEAR)
    assert a.round_price(50000.04) == 50000.0
    assert a.round_price(50000.05) == 50000.1
    assert a.fmt_price(50000.05) == '50000.1'


def spec_A2_float_repr_never_leaks():
    a = SpotAdapter(SPEC_ETH_SPOT)
    # 0.1+0.2 style noise must not survive Decimal-via-str
    assert a.fmt_qty(0.30000000000000004) == '0.3'
    assert 'e' not in a.fmt_qty(0.00001) and 'E' not in a.fmt_qty(0.00001)


# --- A3: the minimum predicate -----------------------------------------------

def spec_A3_meets_minimum_folds_qty_and_notional():
    a = LinearAdapter(SPEC_BTC_LINEAR)
    assert not a.meets_minimum(0.0009, 50000)     # below min_qty
    assert not a.meets_minimum(0.001, 4000)       # 4.0 quote < 5.0 min_notional
    assert a.meets_minimum(0.001, 50000)
    inv = InverseAdapter(SPEC_BTC_INVERSE)
    assert inv.meets_minimum(1, 50000)            # no notional floor on inverse


# --- A4: inverse PnL is base coin; units never mix ---------------------------

def spec_A4_inverse_pnl_is_base_coin():
    inv = InverseAdapter(SPEC_BTC_INVERSE)
    # 100 USD contracts, entry 50,000 exit 51,000:
    # pnl = 100 * (1/50000 - 1/51000) BTC = 100 * (51000-50000)/(50000*51000)
    pnl = inv.realised_pnl(50000.0, 51000.0, 100)
    assert abs(pnl - 100 * 1000 / (50000.0 * 51000.0)) < 1e-15
    assert pnl < 0.001                            # BASE units — tiny number
    # the $396k bug: interpreting that as quote would be absurd; converting is
    # explicit and price-bearing
    assert abs(inv.pnl_to_usd(pnl, 51000.0) - pnl * 51000.0) < 1e-12


def spec_A4_linear_pnl_is_quote_and_conversion_is_identity():
    a = LinearAdapter(SPEC_BTC_LINEAR)
    assert a.realised_pnl(50000.0, 51000.0, 0.002) == 1000.0 * 0.002
    assert a.pnl_to_usd(2.0, 51000.0) == 2.0


def spec_A4_qty_from_notional_per_market_type():
    assert LinearAdapter(SPEC_BTC_LINEAR).qty_from_notional(100.0, 50000.0) == 0.002
    assert InverseAdapter(SPEC_BTC_INVERSE).qty_from_notional(100.0, 50000.0) == 100.0
    assert SpotAdapter(SPEC_ETH_SPOT).qty_from_notional(100.0, 2000.0) == 0.05


# --- A5: positionIdx from (order side, reduce_only), jointly -----------------

def spec_A5_position_idx_matrix():
    hedge = LinearAdapter(SPEC_BTC_LINEAR)
    assert hedge.position_idx('Buy', False) == 1    # opening a long
    assert hedge.position_idx('Sell', True) == 1    # closing a long
    assert hedge.position_idx('Sell', False) == 2   # opening a short
    assert hedge.position_idx('Buy', True) == 2     # closing a short
    oneway = LinearAdapter({**SPEC_BTC_LINEAR, 'one_way_mode': True})
    assert oneway.position_idx('Buy', False) == 0
    assert InverseAdapter(SPEC_BTC_INVERSE).position_idx('Sell', False) == 0
    assert SpotAdapter(SPEC_ETH_SPOT).position_idx('Buy', False) is None


def spec_A5_capabilities_by_market_type():
    assert SpotAdapter(SPEC_ETH_SPOT).supports_short is False
    assert SpotAdapter(SPEC_ETH_SPOT).reports_avg_entry is False
    assert InverseAdapter(SPEC_BTC_INVERSE).one_way_mode is True


# --- A6: the seam — registry, and USDT/USDC as one adapter -------------------

def spec_A6_registry_is_the_seam():
    a = adapter_for('linear', SPEC_BTC_LINEAR)
    assert isinstance(a, LinearAdapter)
    usdc = adapter_for('linear', {**SPEC_BTC_LINEAR, 'symbol': 'BTCPERP',
                                  'settle_coin': 'USDC'})
    assert isinstance(usdc, LinearAdapter)         # settle is data, not a fork
    assert usdc.settle_coin == 'USDC'


def spec_A6_module_is_pure_no_network_no_clock():
    src = Path('gridgremlin/adapters.py').read_text()
    for banned in ('urllib', 'socket', 'http', 'requests', 'time.', 'datetime'):
        assert banned not in src, f'adapters.py must stay pure: found {banned!r}'


# --- the C5 seam from slice 1 now runs against the real thing ----------------

def spec_C5_check_placeable_works_with_a_real_adapter():
    from gridgremlin.config import ConfigError, validate_config, check_placeable
    cfg = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                           'side': 'long', 'capital': 1000.0, 'leverage': 10,
                           'upper': 70000.0, 'lower': 50000.0, 'rungs': 21})
    assert check_placeable(cfg, LinearAdapter(SPEC_BTC_LINEAR))
    dust = validate_config({'market_type': 'linear', 'symbol': 'BTCUSDT',
                            'side': 'long', 'capital': 2.0, 'leverage': 1,
                            'upper': 70000.0, 'lower': 50000.0, 'rungs': 30})
    try:
        check_placeable(dust, LinearAdapter(SPEC_BTC_LINEAR))
    except ConfigError as e:
        assert 'cannot place a single order' in str(e)
    else:
        raise AssertionError('dust config was accepted against the real adapter')
