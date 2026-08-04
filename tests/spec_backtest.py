# Specs for SPEC T3 (trade-through, funding, honesty) and T4 (the v2 diff).

import json
import subprocess
from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.backtest import backtest
from gridgremlin.config import validate_config
from gridgremlin.ladder import plan_grid

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
V2 = Path.home() / 'dev/projects/grid-gremlin-v2'


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


def _bar(o, h, l, c):
    return {'o': o, 'h': h, 'l': l, 'c': c}


# --- T3: trade-through, never touch ------------------------------------------

def spec_T3_touch_is_not_a_fill():
    touched = backtest(_cfg(), ADAPTER, [_bar(60000, 60500, 59000.0, 60000)])
    assert touched.get('entry_fills') == 0        # low == rung: NO fill
    through = backtest(_cfg(), ADAPTER, [_bar(60000, 60500, 58995.0, 60000)])
    assert through['entry_fills'] == 1            # low < rung: fill


def spec_T3_a_round_trip_earns_spacing_minus_fees():
    bars = [_bar(60000, 60050, 58995.0, 59200),   # 59k entry fills
            _bar(59500, 60050.0, 59400, 60000)]   # 60k exit fills (>59,059 floor)
    r = backtest(_cfg(), ADAPTER, bars, fee_rate=0.0002)
    assert r['trips'] == 1 and r['held'] == 0.0 and r['basis'] is None
    assert abs(r['grid_profit'] - 1000.0 * 0.008) < 1e-9   # rung qty, not lot
    assert 0 < r['fees'] < r['grid_profit']
    assert abs(r['net'] - (r['grid_profit'] - r['fees'])) < 1e-9


def spec_T3_funding_bleeds_a_held_position():
    bars = [_bar(60000, 60050, 58995.0, 59000)] + [
        _bar(59000, 59050, 58999.0, 59000)] * 5   # hold 5 quiet bars
    r = backtest(_cfg(), ADAPTER, bars, funding_rate_hourly=1e-4)
    assert r['funding'] > 0                       # a long pays positive funding
    assert abs(r['funding'] - sum(0.007 * 59000 * 1e-4 for _ in range(5))
               - 0.007 * 59000 * 1e-4) < 1.0


def spec_T3_the_honesty_case_grid_profit_up_total_down():
    # the v1 backtester booked +54 on a crash that cost -151. Trade-through +
    # mark-to-market: a crash shows small realized profit and a NEGATIVE total.
    crash = [_bar(60000, 60050, 58995.0, 59000),
             _bar(59000, 59050, 56995.0, 57000),
             _bar(57000, 57050, 54995.0, 55000),
             _bar(55000, 55050, 52995.0, 53000)]
    r = backtest(_cfg(), ADAPTER, crash)
    assert r['grid_profit'] >= 0
    assert r['total'] < 0                         # the truth v1 hid
    assert r['max_drawdown'] > 0


def spec_T3_replay_uses_the_real_plan():
    import inspect
    import gridgremlin.backtest as bt
    src = inspect.getsource(bt)
    assert 'plan_grid' in src                     # T3: no second engine
    assert 'def plan' not in src


# --- T4: v3 diffed against v2 on shared fixtures -----------------------------

V2_SCRIPT = r'''
import json, sys
sys.path.insert(0, {v2root!r})
from gridgremlin.config import validate_config
from gridgremlin.exchange.adapters import LinearAdapter
from gridgremlin.strategy.grid import plan_grid
fix = json.loads(sys.argv[1])
cfg = validate_config(fix['row'])
adapter = LinearAdapter(fix['spec'])
truth = {{'ref': fix['ref'], 'mark': fix['ref'], 'orders': [],
          'positions': {{int(k): v for k, v in fix['positions'].items()}}}}
orders = plan_grid(cfg, truth, adapter, 'diffbot')
print(json.dumps(sorted([o['side'], o['price'], o['qty'], bool(o['reduce_only'])]
                        for o in orders)))
'''


def _v2_plan(row, spec, ref, positions):
    fix = json.dumps({'row': row, 'spec': spec, 'ref': ref,
                      'positions': positions})
    out = subprocess.run(
        ['python3', '-c', V2_SCRIPT.format(v2root=str(V2)), fix],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, f'v2 harness failed: {out.stderr[-500:]}'
    return sorted(tuple(o) for o in json.loads(out.stdout))


def _v3_plan(ref, held=0.0, basis=None, qty_step=0.001):
    spec = {'symbol': 'BTCUSDT', 'qty_step': qty_step, 'price_tick': 0.1,
            'min_qty': qty_step, 'min_notional': 5.0, 'settle_coin': 'USDT'}
    adapter = LinearAdapter(spec)
    orders = plan_grid(_cfg(), adapter, ref, held, basis)
    return sorted((o['side'], o['price'], o['qty'], bool(o['reduce_only']))
                  for o in orders)


def _v2_row():
    return {'category': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
            'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
            'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}


def _v2_spec(qty_step=0.001):
    return {'symbol': 'BTCUSDT', 'qty_step': qty_step, 'price_tick': 0.1,
            'min_qty': qty_step, 'min_notional': 5.0, 'settle_coin': 'USDT'}


def spec_T4_flat_plans_match_v2_exactly():
    assert V2.exists(), 'v2 checkout missing — T4 needs it'
    v2 = _v2_plan(_v2_row(), _v2_spec(), 60000.0, {})
    assert _v3_plan(60000.0) == v2


def spec_T4_adopt_in_profit_matches_v2():
    positions = {1: {'position_idx': 1, 'side': 'Buy', 'size': 0.021,
                     'avg_entry': 55000.0}}
    v2 = _v2_plan(_v2_row(), _v2_spec(), 60000.0, positions)
    assert _v3_plan(60000.0, held=0.021, basis=55000.0) == v2


def spec_T4_adopt_underwater_matches_v2():
    positions = {1: {'position_idx': 1, 'side': 'Buy', 'size': 0.021,
                     'avg_entry': 65000.0}}
    v2 = _v2_plan(_v2_row(), _v2_spec(), 60000.0, positions)
    assert _v3_plan(60000.0, held=0.021, basis=65000.0) == v2


def spec_T4_the_lot_anchor_divergence_is_intended_and_cited():
    # D5: v2 re-prices the lot at the nearest exit rung when holding; v3 uses
    # the split ref always. At a fine qty step the units differ — this is the
    # one intended divergence, decided 2026-08-04.
    step = 0.0001
    positions = {1: {'position_idx': 1, 'side': 'Buy', 'size': 0.0237,
                     'avg_entry': 55000.0}}
    v2 = _v2_plan(_v2_row(), _v2_spec(step), 60000.0, positions)
    v3 = _v3_plan(60000.0, held=0.0237, basis=55000.0, qty_step=step)
    v2_sells = [(p, q) for s, p, q, ro in v2 if s == 'Sell']
    v3_sells = [(p, q) for s, p, q, ro in v3 if s == 'Sell']
    assert {p for p, _ in v2_sells} == {p for p, _ in v3_sells}   # same rungs
    assert v2_sells != v3_sells                                   # D5: unit moved
    v2_lot = min(q for _, q in v2_sells)
    v3_lot = min(q for _, q in v3_sells)
    assert v2_lot != v3_lot and abs(v2_lot - v3_lot) <= 2 * step
