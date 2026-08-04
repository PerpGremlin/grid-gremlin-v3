# Specs for SPEC M3-M6 — the martingale round against the fake venue.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier

from spec_loop import FakeVenue

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


def _bot(venue, lines, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1)


# --- the round opens: base at market, TP before anything rests (M3) ----------

def spec_M3_round_opens_base_then_tp_then_safety_ladder():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    first = bot.cycle()
    assert first == {'round_started': 1}
    assert venue.position and venue.orders == []       # base filled, nothing rests
    counts = bot.cycle()
    assert venue.tp_calls                              # M3: the TP exists...
    assert venue.position.get('takeProfit')
    safeties = [o for o in venue.orders if o['side'] == 'Buy']
    assert len(safeties) == 2 and counts['desired'] == 3   # -7% waits outside
    assert abs(venue.tp_calls[0] - 60000.0 * 1.01) < 0.11  # the window (W1);
    # M4: avg x (1+pct)


def spec_M4_tp_recomputes_when_fills_deepen():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.cycle()
    bot.cycle()
    s1 = next(o for o in venue.orders if o['side'] == 'Buy')
    old_size = float(venue.position['size'])
    add = float(s1['qty'])
    new_avg = ((60000.0 * old_size + s1['price'] * add) / (old_size + add))
    venue.orders = [o for o in venue.orders if o is not s1]
    venue.position = {'positionIdx': 1, 'side': 'Buy',
                      'size': str(old_size + add), 'avgPrice': str(new_avg),
                      'takeProfit': venue.position['takeProfit'],
                      'leverage': '10', 'unrealisedPnl': '0'}
    bot.cycle()
    assert abs(venue.tp_calls[-1] - new_avg * 1.01) < 0.11   # followed the avg


# --- M3: a target the market ran through closes at target or better ----------

def spec_M3_through_market_closes_with_reduce_only_limit():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}          # no TP on the venue
    venue.mark = 60000.0                             # target 59590 already met
    bot = _bot(venue, lines)
    result = bot.cycle()
    assert result == {'round': 'closing'}
    close = venue.orders[-1]
    assert close['side'] == 'Sell' and close['reduce_only']
    assert abs(close['price'] - 59000.0 * 1.01) < 0.11
    assert venue.tp_calls == [] if hasattr(venue, 'tp_calls') else True
    assert any(' tp ' in ln and 'already met' in ln for ln in lines)


# --- M6: restart adopts the resting TP, never rewrites a live round ----------

def spec_M6_restart_believes_the_venue_tp():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'takeProfit': '59700',
                      'leverage': '10', 'unrealisedPnl': '0'}
    bot = _bot(venue, lines)                          # a fresh process
    bot.cycle()
    assert not getattr(venue, 'tp_calls', [])         # adopted, not rewritten


def spec_M6_a_holding_round_with_no_tp_still_gets_one():
    venue, lines = FakeVenue(), []
    venue.mark = 59000.0                              # target above mark: settable
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.016',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines)
    bot.cycle()
    assert venue.tp_calls                             # never without an exit


# --- M5: repeat re-anchors from flat; off means done -------------------------

def spec_M5_repeat_reanchors_a_new_round_at_market():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines, repeat=True)
    bot.cycle()                                       # round 1 base
    bot.cycle()                                       # TP + ladder
    venue.position = None                             # TP hit: flat
    venue.mark = 61000.0
    result = bot.cycle()
    assert result == {'round_started': 2}
    assert any(' repeat ' in ln for ln in lines)
    assert float(venue.position['avgPrice']) == 61000.0   # anchored at market
    assert bot.alive


def spec_M5_repeat_off_round_complete_kills():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.cycle()
    bot.cycle()
    venue.position = None                             # TP hit
    bot.cycle()
    assert bot.alive is False
    assert venue.orders == []                         # stale safeties cancelled
    assert any('round complete' in ln for ln in lines)
