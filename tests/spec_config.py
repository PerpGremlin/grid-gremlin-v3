# Specs for SPEC C1-C7 and G2's config half. Names carry the IDs they pin (T1/T5).

from gridgremlin.config import (ConfigError, RENAMED, RETIRED, GRID_KEYS,
                                validate_config, validate_fleet, check_placeable)

ROW = {
    'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
    'capital': 1000.0, 'leverage': 10, 'upper': 70000.0, 'lower': 50000.0,
    'rungs': 21,
}


def _row(**over):
    r = dict(ROW)
    r.update(over)
    return r


def _refused(row, *fragments):
    try:
        validate_config(row)
    except ConfigError as e:
        msg = str(e)
        for frag in fragments:
            assert frag in msg, f'expected {frag!r} in refusal: {msg!r}'
        return msg
    raise AssertionError(f'config was accepted, expected refusal: {fragments}')


# --- C1: unknown keys refused at every level, one machinery ------------------

def spec_C1_unknown_key_refused_with_near_miss_hint():
    msg = _refused(_row(spacing_pcnt=0.01), 'unknown key', "'spacing_pcnt'")
    assert "did you mean 'spacing_pct'" in msg


def spec_C1_comment_keys_are_legal_at_every_level():
    cfg = validate_config(_row(_note='why this grid exists',
                               stop={'watch': 'mark_price', 'level': 48000,
                                     '_why': 'thesis dies here'}))
    assert '_note' not in cfg


def spec_C1_nested_stop_subkeys_are_enumerated():
    _refused(_row(stop={'watch': 'mark_price', 'level': 48000, 'trigger': 'Mark'}),
             '.stop', "unknown key 'trigger'")


def spec_C1_fleet_level_uses_the_same_machinery():
    try:
        validate_fleet({'bots': [dict(ROW)], 'poll_secondss': 5})
    except ConfigError as e:
        assert "did you mean 'poll_seconds'" in str(e)
    else:
        raise AssertionError('fleet accepted an unknown key')


# --- C2: renames and retirements refuse with the migration stated ------------

def spec_C2_renamed_keys_state_the_migration():
    for old, (new, _) in RENAMED.items():
        if old in ('type', 'value'):
            continue  # stop-shaped; covered below
        msg = _refused(_row(**{old: 1}), old if old in ('investment',) else new)
        assert new in msg, f'{old}: message must name {new}: {msg!r}'


def spec_C2_stop_shape_renames_state_the_migration():
    _refused(_row(stop={'type': 'price', 'value': 48000}), "'type' is now 'watch'")


def spec_C2_retired_keys_state_the_reason():
    for old, reason in RETIRED.items():
        msg = _refused(_row(**{old: 1}))
        assert msg.endswith(reason) or reason in msg, f'{old}: {msg!r}'


def spec_C2_no_old_key_is_silently_accepted():
    # the completeness half of the refusal table: every RENAMED/RETIRED key is
    # genuinely outside the accepted set
    for old in list(RENAMED) + list(RETIRED):
        if old in ('type', 'value'):
            continue  # stop sub-keys, not row keys
        assert old not in GRID_KEYS, f'{old} is still an accepted key'


# --- C3: one bounds convention; leverage finally validated -------------------

def spec_C3_fractions_share_one_interval_convention():
    _refused(_row(place_within_pct=0))       # zero is not 'off' here
    _refused(_row(place_within_pct=1.0))     # fractions are open above
    _refused(_row(place_within_pct=50))      # v2 allowed this; v3 does not
    assert validate_config(_row(place_within_pct=0.05))
    # zero_means_off keys admit 0 and it equals unset
    a = validate_config(_row(split_hysteresis_rungs=0))
    b = validate_config(dict(ROW))
    assert a['split_hysteresis_rungs'] == b['split_hysteresis_rungs'] == 0.0
    _refused(_row(split_hysteresis_rungs=0.6))  # bounded at 0.5


def spec_C3_leverage_is_validated():
    _refused(_row(leverage=0))
    _refused(_row(leverage=-40))
    _refused(_row(leverage='40'))
    _refused(_row(leverage=126))
    assert validate_config(_row(leverage=40))['leverage'] == 40.0


def spec_C3_booleans_never_pass_as_numbers():
    _refused(_row(capital=True))
    _refused(_row(rungs=True, spacing_pct=None))


# --- C4: derived values written back once; supplying one is refused ----------

def spec_C4_ladder_notional_derived_and_input_refused():
    cfg = validate_config(dict(ROW))
    assert cfg['ladder_notional'] == 1000.0 * 10
    _refused(_row(notional=8000), 'derived, not configured')


def spec_C4_spot_derives_without_leverage_unless_borrowing():
    spot = _row(market_type='spot', side='long', leverage=None)
    cfg = validate_config(spot)
    assert cfg['ladder_notional'] == 1000.0
    cfg = validate_config(_row(market_type='spot', side='long', leverage=None,
                               spot_borrow=True, spot_leverage=3))
    assert cfg['ladder_notional'] == 3000.0


# --- C5: a cannot-place config refuses with the reason -----------------------

class _FakeAdapter:
    def __init__(self, min_notional):
        self.min_notional = min_notional

    def qty_from_notional(self, notional, price):
        return notional / price

    def meets_minimum(self, qty, price):
        return qty * price >= self.min_notional


def spec_C5_cannot_place_refuses_with_the_numbers():
    cfg = validate_config(dict(ROW))  # ~476 quote per rung
    try:
        check_placeable(cfg, _FakeAdapter(min_notional=500.0))
    except ConfigError as e:
        assert 'cannot place a single order' in str(e)
        assert 'capital' in str(e)
    else:
        raise AssertionError('unplaceable config was accepted')
    assert check_placeable(cfg, _FakeAdapter(min_notional=5.0))


# --- C6: a bad row refuses the whole fleet -----------------------------------

def spec_C6_bad_row_refuses_the_whole_fleet():
    good, bad = dict(ROW), _row(side='shrot')
    try:
        validate_fleet({'bots': [good, bad]})
    except ConfigError as e:
        assert 'bots[1]' in str(e)
    else:
        raise AssertionError('fleet started with a bad row')


def spec_C6_bare_list_gets_the_same_treatment():
    try:
        validate_fleet([dict(ROW), {'symbol': 'ETHUSDT'}])
    except ConfigError as e:
        assert 'bots[1]' in str(e)
    else:
        raise AssertionError('bare-list fleet skipped validation')


# --- C7: error messages name only keys that exist ----------------------------

def spec_C7_messages_name_only_real_keys():
    current = set(GRID_KEYS) | {'watch', 'level', 'bots', 'poll_seconds',
                                'cancel_orders_on_exit', 'notify_orders',
                                'max_averaging_orders', 'order_size_multiplier'}
    for old, (new, msg) in RENAMED.items():
        assert new in current, f"RENAMED points at nonexistent key '{new}'"
        assert old not in msg.split("'")[0], msg
    # retirement messages may cite decisions/docs, but any quoted key must exist
    for old, msg in RETIRED.items():
        for token in msg.split("'")[1::2]:
            if token.islower() and '_' in token:
                assert token in current, (
                    f"RETIRED message for '{old}' names nonexistent key "
                    f"'{token}': {msg!r}")


# --- misc doctrine earned by v2 incidents ------------------------------------

def spec_G2_supplied_spacing_is_reconciled_with_the_lattice():
    cfg = validate_config(_row(rungs=None, spacing_pct=0.01))
    n = cfg['rungs']
    assert n >= 2
    expected = (70000.0 / 50000.0) ** (1.0 / (n - 1)) - 1.0
    assert abs(cfg['spacing_pct'] - expected) < 1e-12  # stored = actual gap


def spec_strategy_is_normalised_back_for_grid_too():
    assert validate_config(dict(ROW))['strategy'] == 'grid'  # config M14's fix


def spec_D24_spot_short_needs_borrow():
    _refused(_row(market_type='spot', side='short', leverage=None),
             "needs 'spot_borrow'")
    cfg = validate_config(_row(market_type='spot', side='short', leverage=None,
                               spot_borrow=True, spot_leverage=2))
    assert cfg['side'] == 'short' and cfg['leverage'] == 2.0


def spec_D24_borrow_and_leverage_come_together():
    _refused(_row(market_type='spot', side='long', leverage=None,
                  spot_borrow=True), "needs 'spot_leverage'")
    _refused(_row(market_type='spot', side='long', leverage=None,
                  spot_leverage=3), 'half a directive')
    cfg = validate_config(_row(market_type='spot', side='long', leverage=None,
                               spot_borrow=True, spot_leverage=3))
    assert cfg['leverage'] == 3.0      # D24: sizing flows the one normal path


def spec_D24_spot_refuses_the_plain_leverage_key():
    _refused(_row(market_type='spot', side='long', leverage=5),
             "does not take 'leverage'")


def spec_booleans_coerce_unconditionally():
    cfg = validate_config(_row(market_type='spot', side='long',
                               leverage=None, spot_borrow=0))
    assert cfg['spot_borrow'] is False  # M16: never coerced inside an `if`


def spec_stop_position_sl_takes_no_level():
    _refused(_row(stop={'watch': 'position_sl', 'level': 48000}),
             "'level' does not apply")
    cfg = validate_config(_row(stop={'watch': 'position_sl'}))
    assert cfg['stop'] == {'watch': 'position_sl', 'server_side': False}


def spec_stop_account_equity_level_floor():
    _refused(_row(stop={'watch': 'account_equity', 'level': 0.2}))  # the old % trap
    assert validate_config(_row(stop={'watch': 'account_equity', 'level': 2500}))


def spec_assumed_avg_entry_is_spot_only():
    _refused(_row(assumed_avg_entry=60000), "'spot' only")


def spec_martingale_rows_validate_with_their_own_keyset():
    cfg = validate_config({'strategy': 'martingale', 'market_type': 'linear',
                           'symbol': 'ETHUSDT', 'side': 'short',
                           'capital': 500.0, 'leverage': 5,
                           'base_order_size': 200.0, 'safety_order_size': 200.0,
                           'deviation_pct': 0.02, 'max_averaging_orders': 3,
                           'take_profit_avg_pct': 0.015})
    assert cfg['strategy'] == 'martingale'
    assert cfg['ladder_total_notional'] == 800.0
    _refused({'strategy': 'martingale', 'symbol': 'ETHUSDT'})  # side etc. required


def _mrow(**over):
    row = dict(strategy='martingale', market_type='linear', symbol='BTCUSDT',
               side='long', capital=1000, base_order_size=100,
               safety_order_size=100, deviation_pct=0.01,
               max_averaging_orders=2)
    row.update(over)
    return row


def spec_D23_tranches_and_single_tp_are_one_question():
    _refused(_mrow(take_profit_avg_pct=0.01,
                   take_profit_tranches=[{'at_avg_pct': 0.01, 'share': 1.0}]),
             'pick one')
    _refused(_mrow(), 'never without an exit')


def spec_D23_tranche_shares_sum_to_one_and_ascend():
    _refused(_mrow(take_profit_tranches=[
        {'at_avg_pct': 0.01, 'share': 0.5},
        {'at_avg_pct': 0.02, 'share': 0.4}]), 'sum to')
    _refused(_mrow(take_profit_tranches=[
        {'at_avg_pct': 0.02, 'share': 0.5},
        {'at_avg_pct': 0.01, 'share': 0.5}]), 'ascend')
    cfg = validate_config(_mrow(take_profit_tranches=[
        {'at_avg_pct': 0.01, 'share': 0.5},
        {'at_avg_pct': 0.02, 'share': 0.5}]))
    assert len(cfg['take_profit_tranches']) == 2


def spec_D23_trailing_refuses_the_hostless_venue():
    _refused(_mrow(take_profit_avg_pct=0.01, venue='hyperliquid',
                   trailing_stop_pct=0.01), 'hosts trailing')


def spec_F8_preflight_validates_and_defaults_off():
    fleet = validate_fleet({'watchdog': 'w.json', 'bots': [dict(ROW)]})
    assert fleet['preflight'] == {'probe': False, 'max_failed_bots': 0}
    fleet = validate_fleet({'watchdog': 'w.json', 'bots': [dict(ROW)],
                            'preflight': {'probe': True,
                                          'max_failed_bots': 2}})
    assert fleet['preflight']['probe'] is True
    try:
        validate_fleet({'watchdog': 'w.json', 'bots': [dict(ROW)],
                        'preflight': {'probes': True}})
    except ConfigError as e:
        assert 'probes' in str(e)
    else:
        raise AssertionError('unknown preflight key accepted')
