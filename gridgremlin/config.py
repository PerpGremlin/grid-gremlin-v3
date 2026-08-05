# Config doctrine (SPEC C1-C7). The RENAMED/RETIRED tables are
# docs/MIGRATION.md's refusal column, all of it. The why lives in docs/SPEC.md.

import difflib

MATCH_CUTOFF = 0.7  # the one difflib cutoff (C1)

VENUES = ('bybit', 'hyperliquid')
MARKET_TYPES = ('linear', 'inverse', 'spot')
SIDES = ('long', 'short')
STRATEGIES = ('grid', 'martingale')
SPACING_TYPES = ('percent', 'fixed')
RUNG_SIZINGS = ('equal', 'weighted')
STOP_WATCHES = ('mark_price', 'account_equity', 'position_sl')
UNBOUNDED = 'unbounded'

COMMON_KEYS = ('venue', 'market_type', 'symbol', 'side', 'strategy', 'capital',
               'leverage', 'stop')
GRID_KEYS = COMMON_KEYS + (
    'upper', 'lower', 'rungs', 'spacing_pct', 'spacing_type', 'rung_sizing',
    'rung_weights', 'place_within_pct', 'split_hysteresis_rungs',
    'assumed_avg_entry', 'min_position_base', 'max_position_base',
    'spot_borrow', 'spot_leverage', 'seed')
MARTINGALE_KEYS = COMMON_KEYS + (
    'take_profit_tranches', 'trailing_stop_pct',
    'base_order_size', 'safety_order_size', 'order_size_multiplier',
    'deviation_pct', 'deviation_step_multiplier', 'max_averaging_orders',
    'take_profit_avg_pct', 'repeat', 'place_within_pct')
STOP_KEYS = ('watch', 'level', 'server_side')
FLEET_KEYS = ('bots', 'poll_seconds', 'cancel_orders_on_exit', 'allow_mainnet',
              'tombstones',
              'notify_orders', 'watchdog')

# C2 — renames. old key -> (new key, message).
RENAMED = {
    'investment': ('capital', "renamed: 'investment' is now 'capital' — the quote margin "
                   "you commit; the engine derives exposure as capital x leverage"),
    'category': ('market_type', "renamed: 'category' is now 'market_type' "
                 "(linear / inverse / spot)"),
    'split_deadband_rungs': ('split_hysteresis_rungs', "renamed: "
                             "'split_deadband_rungs' is now 'split_hysteresis_rungs'"),
    'type': ('watch', "stop is restructured: 'type' is now 'watch' "
             "(mark_price / account_equity / position_sl)"),
    'value': ('level', "stop is restructured: 'value' is now 'level'"),
}

# C2 — retirements. old key -> message. The concept left v3 (docs/MIGRATION.md).
RETIRED = {
    'notional': "derived, not configured: the engine computes capital x leverage "
                "itself — remove it (set 'capital')",
    'no_trade_pct': "retired: the no-trade behaviour is emergent (DECISIONS D6) — "
                    "the suppression around an adopted basis needs no key",
    'entry_deadband_pct': "retired: the no-trade band family left v3 (DECISIONS D6)",
    'exit_deadband_pct': "retired: the no-trade band family left v3 (DECISIONS D6)",
    'exit_markup_pct': "retired: the fee floor is an internal constant (SPEC G6), "
                       "not a knob",
    'exit_against': "retired: the exit floor is unconditional (SPEC G6) — there is "
                    "no 'rung' bypass",
    'arm_order': "retired: entries arm nearest-first; furthest-first returns only "
                 "with a spec and a user (docs/MIGRATION.md)",
    'trail': "retired: edit 'upper'/'lower' instead — range edits flow through the "
             "normal diff (DECISIONS D10)",
    'sma_periods': "retired: the trail feature left v3 (DECISIONS D10)",
    'trail_min': "retired: the trail feature left v3 (DECISIONS D10)",
    'trail_max': "retired: the trail feature left v3 (DECISIONS D10)",
    'levels': "martingale is restructured (DECISIONS D11): a base order plus "
              "'max_averaging_orders' safety orders — see docs/MIGRATION.md #3",
    'level_weights': "martingale is restructured (DECISIONS D11): sizing is "
                     "'order_size_multiplier' of the previous order",
    'first_entry': "martingale is restructured (DECISIONS D11): the round starts "
                   "from a base order — see docs/MIGRATION.md #3",
    'take_profit_price': "retired: the absolute take-profit left with the "
                         "restructure (DECISIONS D11/D12); targets are relative",
}


class ConfigError(ValueError):
    """The one exception for every config refusal (C1)."""


def _refuse(msg):
    raise ConfigError(msg)


def _reject_unknown(given, allowed, where):
    """C1: unknown keys are refused at every level; '_'-prefixed keys are comments."""
    for key in given:
        if key.startswith('_') or key in allowed:
            continue
        if key in RENAMED:
            _refuse(f'{where}: {RENAMED[key][1]}')
        if key in RETIRED:
            _refuse(f'{where}: {RETIRED[key]}')
        hint = difflib.get_close_matches(key, allowed, n=1, cutoff=MATCH_CUTOFF)
        did = f" — did you mean '{hint[0]}'?" if hint else ''
        _refuse(f"{where}: unknown key '{key}'{did}")


# --- C3: the bounds helpers. Every numeric passes through one of these. -------

def _num(row, key, where, *, least=None, most=None, least_open=False,
         most_open=False, required=False, integer=False):
    v = row.get(key)
    if v is None:
        if required:
            _refuse(f"{where}: '{key}' is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _refuse(f"{where}: '{key}' must be a number")
    if integer and int(v) != v:
        _refuse(f"{where}: '{key}' must be an integer")
    if least is not None and (v <= least if least_open else v < least):
        _refuse(f"{where}: '{key}' must be {'>' if least_open else '>='} {least}")
    if most is not None and (v >= most if most_open else v > most):
        _refuse(f"{where}: '{key}' must be {'<' if most_open else '<='} {most}")
    return int(v) if integer else float(v)


def _fraction(row, key, where, *, zero_means_off=False, most=1.0):
    """C3: the one interval convention for fraction-valued keys — (0, most),
    with zero admitted only where zero means 'off' and is identical to unset."""
    return _num(row, key, where, least=0.0, least_open=not zero_means_off,
                most=most, most_open=True)


def _enum(row, key, where, allowed, default=None):
    v = row.get(key, default)
    if v not in allowed:
        _refuse(f"{where}: '{key}' must be one of {allowed}")
    return v


def _flag(row, key):
    """M16's lesson: coerce booleans unconditionally, never inside an `if`."""
    return bool(row.get(key, False))


# --- the validators -----------------------------------------------------------

def _validate_stop(stop, where):
    """X2's shape. Sub-keys are enumerated — C1 does not stop at the row level."""
    if stop is None:
        return None
    if not isinstance(stop, dict):
        _refuse(f"{where}: 'stop' must be an object")
    _reject_unknown(stop, STOP_KEYS, f'{where}.stop')
    watch = _enum(stop, 'watch', f'{where}.stop', STOP_WATCHES)
    server = _flag(stop, 'server_side')
    if server and watch != 'mark_price':
        _refuse(f"{where}.stop: server_side applies to watch: mark_price only — "
                "account_equity lives in-process; position_sl IS the "
                'venue-hosted stop')
    if watch == 'position_sl':
        if 'level' in stop:
            _refuse(f"{where}.stop: 'level' does not apply to watch: position_sl — "
                    "the level is the stop-loss you placed on the venue")
        return {'watch': watch, 'server_side': False}
    least = 1.0 if watch == 'account_equity' else 0.0
    level = _num(stop, 'level', f'{where}.stop', least=least, least_open=(least == 0.0),
                 required=True)
    return {'watch': watch, 'level': level, 'server_side': server}


def _derive_rungs(cfg, where):
    """G2: exactly one of rungs/spacing_pct given; the other derives; the stored
    pair is reconciled — the config never carries a spacing the lattice lacks."""
    import math
    has_n = cfg.get('rungs') is not None
    has_s = cfg.get('spacing_pct') is not None
    if has_n == has_s:
        _refuse(f"{where}: give exactly one of 'rungs' or 'spacing_pct'")
    upper, lower = cfg['upper'], cfg['lower']
    if has_s:
        s = _num(cfg, 'spacing_pct', where, least=0.0, least_open=True)
        if cfg['spacing_type'] == 'percent':
            n = max(2, int(math.log(upper / lower) / math.log(1.0 + s)) + 1)
        else:
            n = max(2, int(round((upper - lower) / s)) + 1)
        cfg['rungs'] = n
    n = _num(cfg, 'rungs', where, least=2, required=True, integer=True)
    cfg['rungs'] = n
    # reconcile: store the gap the lattice will actually have (N-1 divisor, G3)
    if cfg['spacing_type'] == 'percent':
        cfg['spacing_pct'] = (upper / lower) ** (1.0 / (n - 1)) - 1.0
    else:
        cfg['spacing_pct'] = (upper - lower) / (n - 1)


def validate_grid(row, where='row'):
    _reject_unknown(row, GRID_KEYS, where)
    cfg = {k: v for k, v in row.items() if not k.startswith('_')}

    cfg['venue'] = _enum(cfg, 'venue', where, VENUES, default='bybit')
    cfg['market_type'] = _enum(cfg, 'market_type', where, MARKET_TYPES)
    if not isinstance(cfg.get('symbol'), str) or not cfg.get('symbol'):
        _refuse(f"{where}: 'symbol' must be a non-empty string")
    cfg['side'] = _enum(cfg, 'side', where, SIDES)
    if cfg['market_type'] == 'spot' and cfg['side'] == 'short' \
            and not cfg.get('spot_borrow'):
        _refuse(f"{where}: a spot short needs 'spot_borrow': true — only "
                'borrow can sell what is not held (D24)')
    if cfg['market_type'] == 'spot' and cfg.get('leverage') is not None:
        _refuse(f"{where}: spot does not take 'leverage' — borrow sizing is "
                "'spot_leverage' under 'spot_borrow' (D24)")
    cfg['strategy'] = 'grid'  # normalised back for BOTH strategies (config M14)

    capital = _num(cfg, 'capital', where, least=0.0, least_open=True, required=True)
    leverage = _num(cfg, 'leverage', where, least=1.0, most=125.0)
    if leverage is None:
        leverage = 1.0
    cfg['capital'], cfg['leverage'] = capital, leverage

    lower = _num(cfg, 'lower', where, least=0.0, least_open=True, required=True)
    upper = _num(cfg, 'upper', where, least=lower, least_open=True, required=True)
    cfg['lower'], cfg['upper'] = lower, upper

    cfg['spacing_type'] = _enum(cfg, 'spacing_type', where, SPACING_TYPES,
                                default='percent')
    _derive_rungs(cfg, where)

    cfg['rung_sizing'] = _enum(cfg, 'rung_sizing', where, RUNG_SIZINGS,
                               default='equal')
    weights = cfg.get('rung_weights')
    if cfg['rung_sizing'] == 'weighted':
        if (not isinstance(weights, (list, tuple)) or len(weights) != cfg['rungs']
                or not all(isinstance(w, (int, float)) and not isinstance(w, bool)
                           and w > 0 for w in weights)):
            _refuse(f"{where}: weighted sizing needs 'rung_weights' — a list of "
                    f"{cfg['rungs']} positive numbers, one per rung")
        cfg['rung_weights'] = [float(w) for w in weights]
    elif weights is not None:
        _refuse(f"{where}: 'rung_weights' is only read when rung_sizing is "
                "'weighted'")

    w = _fraction(cfg, 'place_within_pct', where)
    cfg['place_within_pct'] = 0.05 if w is None else w
    h = _fraction(cfg, 'split_hysteresis_rungs', where, zero_means_off=True, most=0.5)
    cfg['split_hysteresis_rungs'] = 0.0 if h is None else h

    aae = _num(cfg, 'assumed_avg_entry', where, least=0.0, least_open=True)
    if aae is not None and cfg['market_type'] != 'spot':
        _refuse(f"{where}: 'assumed_avg_entry' applies to market_type 'spot' only — "
                "derivative venues report the average entry themselves")

    floor = _num(cfg, 'min_position_base', where, least=0.0)
    cfg['min_position_base'] = 0.0 if floor is None else floor
    cap = cfg.get('max_position_base')
    if cap is not None and cap != UNBOUNDED:
        cap = _num(cfg, 'max_position_base', where, least=0.0, least_open=True)
        if cap <= cfg['min_position_base']:
            _refuse(f"{where}: 'max_position_base' must exceed 'min_position_base'")
        cfg['max_position_base'] = cap

    cfg['seed'] = _flag(cfg, 'seed')
    cfg['spot_borrow'] = _flag(cfg, 'spot_borrow')
    sl = _num(cfg, 'spot_leverage', where, least=1.0, most=10.0)
    if (cfg['spot_borrow'] or sl is not None) and cfg['market_type'] != 'spot':
        _refuse(f"{where}: 'spot_borrow'/'spot_leverage' apply to market_type "
                "'spot' only")
    if cfg['spot_borrow'] and sl is None:
        _refuse(f"{where}: 'spot_borrow' needs 'spot_leverage' — say the "
                'multiple (D24)')
    if sl is not None and not cfg['spot_borrow']:
        _refuse(f"{where}: 'spot_leverage' without 'spot_borrow' is half a "
                'directive (D24)')
    if cfg['spot_borrow']:
        cfg['spot_leverage'] = sl
        cfg['leverage'] = sl     # D24: sizing flows the one normal path

    cfg['stop'] = _validate_stop(cfg.get('stop'), where)
    if (cfg['stop'] and cfg['stop']['server_side']
            and (cfg['market_type'] == 'spot'
                 or cfg['venue'] == 'hyperliquid')):
        _refuse(f"{where}.stop: server_side needs a venue that hosts "
                'position-level stops — not spot, not hyperliquid (this phase)')

    # C4: the one derived value, written back once.
    eff = 1.0
    if cfg['market_type'] != 'spot':
        eff = leverage
    elif cfg['spot_borrow']:
        eff = cfg.get('spot_leverage', 1.0)
    cfg['ladder_notional'] = capital * eff
    return cfg


def _validate_tranches(v, where):
    """D23: shares of one position, ascending targets, summing to one."""
    if v is None:
        return None
    if not isinstance(v, list) or not v:
        _refuse(f"{where}: 'take_profit_tranches' must be a non-empty list")
    out, last = [], 0.0
    for i, t in enumerate(v):
        w2 = f'{where}.take_profit_tranches[{i}]'
        if not isinstance(t, dict):
            _refuse(f'{w2}: each tranche is {{at_avg_pct, share}}')
        _reject_unknown(t, ('at_avg_pct', 'share'), w2)
        pct = _fraction(t, 'at_avg_pct', w2)
        share = _num(t, 'share', w2, least=0.0, least_open=True, most=1.0)
        if pct is None or share is None or share <= 0:
            _refuse(f'{w2}: at_avg_pct and share are required, share > 0')
        if pct <= last:
            _refuse(f"{where}: tranches must ascend in 'at_avg_pct'")
        last = pct
        out.append({'at_avg_pct': pct, 'share': share})
    total = sum(t['share'] for t in out)
    if abs(total - 1.0) > 1e-6:
        _refuse(f'{where}: tranche shares sum to {total:.10g} — they are '
                'shares of ONE position, they must sum to 1')
    return out


def validate_martingale(row, where='row'):
    _reject_unknown(row, MARTINGALE_KEYS, where)
    cfg = {k: v for k, v in row.items() if not k.startswith('_')}

    cfg['venue'] = _enum(cfg, 'venue', where, VENUES, default='bybit')
    cfg['market_type'] = _enum(cfg, 'market_type', where, ('linear',),
                               default='linear')
    if not isinstance(cfg.get('symbol'), str) or not cfg.get('symbol'):
        _refuse(f"{where}: 'symbol' must be a non-empty string")
    cfg['side'] = _enum(cfg, 'side', where, SIDES)
    cfg['strategy'] = 'martingale'

    capital = _num(cfg, 'capital', where, least=0.0, least_open=True, required=True)
    leverage = _num(cfg, 'leverage', where, least=1.0, most=125.0) or 1.0
    cfg['capital'], cfg['leverage'] = capital, leverage
    cfg['ladder_notional'] = capital * leverage

    cfg['base_order_size'] = _num(cfg, 'base_order_size', where, least=0.0,
                                  least_open=True, required=True)
    cfg['safety_order_size'] = _num(cfg, 'safety_order_size', where, least=0.0,
                                    least_open=True, required=True)
    cfg['order_size_multiplier'] = _num(cfg, 'order_size_multiplier', where,
                                        least=1.0, most=10.0) or 1.0
    cfg['deviation_pct'] = _fraction(cfg, 'deviation_pct', where)
    if cfg['deviation_pct'] is None:
        _refuse(f"{where}: 'deviation_pct' is required")
    cfg['deviation_step_multiplier'] = _num(cfg, 'deviation_step_multiplier',
                                            where, least=1.0, most=10.0) or 1.0
    cfg['max_averaging_orders'] = _num(cfg, 'max_averaging_orders', where,
                                       least=1, most=50, required=True,
                                       integer=True)
    cfg['take_profit_avg_pct'] = _fraction(cfg, 'take_profit_avg_pct', where)
    cfg['take_profit_tranches'] = _validate_tranches(
        cfg.get('take_profit_tranches'), where)
    if cfg['take_profit_avg_pct'] is None and not cfg['take_profit_tranches']:
        _refuse(f"{where}: 'take_profit_avg_pct' (or 'take_profit_tranches') "
                'is required — a round is never without an exit (M3)')
    if cfg['take_profit_avg_pct'] is not None and cfg['take_profit_tranches']:
        _refuse(f"{where}: 'take_profit_avg_pct' and 'take_profit_tranches' "
                'are two answers to one question — pick one (D23)')
    t = _fraction(cfg, 'trailing_stop_pct', where)
    if t is not None:
        if cfg['venue'] == 'hyperliquid':
            _refuse(f"{where}: 'trailing_stop_pct' needs a venue that hosts "
                    'trailing — not hyperliquid this phase (D23)')
        cfg['trailing_stop_pct'] = t
    w = _fraction(cfg, 'place_within_pct', where)
    cfg['place_within_pct'] = 0.05 if w is None else w
    cfg['repeat'] = _flag(cfg, 'repeat')
    cfg['stop'] = _validate_stop(cfg.get('stop'), where)

    # M2: expand the series; refuse a ladder the capital cannot carry.
    k, n = cfg['order_size_multiplier'], cfg['max_averaging_orders']
    total = cfg['base_order_size'] + sum(
        cfg['safety_order_size'] * k ** i for i in range(n))
    if total > cfg['ladder_notional'] + 1e-9:
        margin = total / leverage
        _refuse(f"{where}: the full ladder needs {total:.10g} notional "
                f"({margin:.10g} margin at {leverage:g}x) but capital is "
                f"{capital:.10g} — lower 'max_averaging_orders', "
                "'order_size_multiplier' or the order sizes")
    cfg['ladder_total_notional'] = total
    return cfg


def validate_config(row, where='row'):
    strategy = row.get('strategy', 'grid')
    if strategy not in STRATEGIES:
        _refuse(f"{where}: 'strategy' must be one of {STRATEGIES}")
    if strategy == 'martingale':
        return validate_martingale(row, where)
    return validate_grid(row, where)


def check_placeable(cfg, adapter, where='row'):
    """C5: a config that cannot place a single order refuses at load, with the
    reason and the numbers. Martingale needs a live base price -> slice 12."""
    if cfg['strategy'] == 'martingale':
        return cfg
    weights = cfg.get('rung_weights') or [1.0] * cfg['rungs']
    smallest = cfg['ladder_notional'] * min(weights) / sum(weights)
    qty = adapter.qty_from_notional(smallest, cfg['upper'])
    if not adapter.meets_minimum(qty, cfg['upper']):
        _refuse(f"{where}: cannot place a single order — the smallest rung "
                f"({smallest:.10g} quote, {qty:.10g} base at {cfg['upper']:.10g}) "
                "is below the venue minimum; raise 'capital' or lower 'rungs'")
    return cfg


def validate_fleet(data, where='fleet'):
    """C6: any bad row refuses the whole fleet. A bare list is a fleet whose only
    key is 'bots' — the same key check applies either way (config M15's fix)."""
    if isinstance(data, list):
        data = {'bots': data}
    if not isinstance(data, dict):
        _refuse(f'{where}: a fleet file is an object or a list of rows')
    _reject_unknown(data, FLEET_KEYS, where)
    bots = data.get('bots')
    if not isinstance(bots, list) or not bots:
        _refuse(f"{where}: 'bots' must be a non-empty list")
    fleet = {
        'watchdog': data.get('watchdog'),
        'poll_seconds': _num(data, 'poll_seconds', where, least=0.0,
                             least_open=True) or 5.0,
        'cancel_orders_on_exit': _flag(data, 'cancel_orders_on_exit'),
        'notify_orders': _flag(data, 'notify_orders'),
        'allow_mainnet': _flag(data, 'allow_mainnet'),   # D25: half of the safety
        'tombstones': data.get('tombstones'),            # X7 path (default logs/)
    }
    fleet['bots'] = [validate_config(row, where=f'{where}.bots[{i}]')
                     for i, row in enumerate(bots)]
    return fleet
