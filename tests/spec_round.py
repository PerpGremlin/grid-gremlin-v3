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
    assert result == {'round': 'cleanup'}             # H4b: E2 across rounds —
    assert venue.orders == []                         # stale ladder gone FIRST
    result = bot.cycle()
    assert result == {'round_started': 2}
    assert sum(' repeat ' in ln for ln in lines) == 1     # H4a: once, not 1/cycle
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


# --- D21: the venue-resting exit (HL-style, hosts_position_tp=False) ---------

class FakeHLRound(FakeVenue):
    hosts_position_tp = False

    def set_trading_stop(self, *a, **kw):
        raise AssertionError('a capability-less venue must never be asked')


def _hl_bot(venue, lines, **over):
    from gridgremlin.apply import make_botid
    cfg = _cfg(venue='hyperliquid', **over)
    return Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)


def spec_D21_round_exit_rests_as_reduce_only_order():
    venue, lines = FakeHLRound(), []
    bot = _hl_bot(venue, lines)
    bot.cycle()                                        # base at market
    bot.cycle()                                        # TP + ladder
    tps = [o for o in venue.orders
           if o['reduce_only'] and o['side'] == 'Sell']
    assert len(tps) == 1
    assert abs(tps[0]['price'] - 60000.0 * 1.01) < 0.11
    assert tps[0]['link_id'].startswith('linBTCUSDTl-0-')   # rung 0 reserved
    assert any('TP resting' in ln for ln in lines)


def spec_D21_the_diff_never_cancels_the_round_exit():
    venue, lines = FakeHLRound(), []
    bot = _hl_bot(venue, lines)
    bot.cycle()
    bot.cycle()
    counts = bot.cycle()                               # steady state
    assert counts['cancels'] == 0
    assert sum(1 for o in venue.orders
               if o['reduce_only'] and o['side'] == 'Sell') == 1


def spec_D21_restart_adopts_the_resting_exit_by_identity():
    venue, lines = FakeHLRound(), []
    _hl_bot(venue, lines).cycle() or _hl_bot(venue, lines)
    first = _hl_bot(venue, lines)
    first.cycle()
    first.cycle()
    n_orders = len(venue.orders)
    fresh = _hl_bot(venue, lines)                      # a new process
    fresh.cycle()
    tps = [o for o in venue.orders
           if o['reduce_only'] and o['side'] == 'Sell']
    assert len(tps) == 1 and len(venue.orders) == n_orders   # M6: believed


def spec_D21_deepening_fill_refreshes_the_resting_exit():
    venue, lines = FakeHLRound(), []
    bot = _hl_bot(venue, lines)
    bot.cycle()
    bot.cycle()
    s1 = next(o for o in venue.orders
              if o['side'] == 'Buy' and not o['reduce_only'])
    old_size = float(venue.position['size'])
    add = float(s1['qty'])
    new_avg = (60000.0 * old_size + s1['price'] * add) / (old_size + add)
    venue.orders = [o for o in venue.orders if o is not s1]
    venue.position = dict(venue.position, size=str(old_size + add),
                          avgPrice=str(new_avg))
    bot.cycle()
    tps = [o for o in venue.orders
           if o['reduce_only'] and o['side'] == 'Sell']
    assert len(tps) == 1
    assert abs(tps[0]['price'] - ADAPTER.round_price(new_avg * 1.01)) < 0.11
    assert abs(float(tps[0]['qty']) - (old_size + add)) < 1e-9


# --- I5: the base order carries our identity ---------------------------------

def spec_I5_the_base_order_carries_an_owned_link():
    from gridgremlin.apply import rung_of
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    assert bot.cycle() == {'round_started': 1}
    assert rung_of(venue.market_links[0], bot.botid) == 0


# --- D23: tranches — the same exit law, split into shares --------------------

def _tranche_cfg(**over):
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3,
           'take_profit_tranches': [{'at_avg_pct': 0.01, 'share': 0.5},
                                    {'at_avg_pct': 0.02, 'share': 0.5}]}
    row.update(over)
    return validate_config(row)


def spec_D23_hosted_tranches_rest_on_the_conditional_book():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                    # base at market
    bot.cycle()                                    # tranches maintained
    book = venue.stop_orders('linear', 'BTCUSDT')
    assert len(book) == 2
    prices = sorted(float(o['triggerPrice']) for o in book)
    assert prices == [60600.0, 61200.0]            # +1% and +2% of 60000
    qtys = {o['qty'] for o in book}
    assert qtys == {'0.008'}                       # half of 0.016 each
    n = len(book)
    bot.cycle()                                    # level-triggered: no churn
    assert len(venue.stop_orders('linear', 'BTCUSDT')) == n


def spec_D23_tranches_reanchor_when_the_average_moves():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    bot.cycle()
    venue.position = dict(venue.position, size='0.032', avgPrice='59500')
    bot.cycle()                                    # deepen: re-anchored
    book = venue.stop_orders('linear', 'BTCUSDT')
    assert len(book) == 2
    assert sorted(float(o['triggerPrice']) for o in book) == [60095.0, 60690.0]
    assert {o['qty'] for o in book} == {'0.016'}


def spec_D23_the_hostless_venue_gets_a_tranche_ladder():
    venue, lines = FakeHLRound(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    bot.cycle()
    from gridgremlin.apply import rung_of
    exits = [o for o in venue.orders
             if o['reduce_only'] and o['side'] == 'Sell'
             and rung_of(o['link_id'], bot.botid) == 0]
    assert len(exits) == 2
    assert sorted(o['price'] for o in exits) == [60600.0, 61200.0]
    n = len(venue.orders)
    bot.cycle()                                    # adopted by identity
    assert len(venue.orders) == n


def spec_D23_trailing_rides_the_venue_once_per_round():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(take_profit_tranches=None,
                           take_profit_avg_pct=0.01,
                           trailing_stop_pct=0.01),
              ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    bot.cycle()
    assert venue.trail_calls == [600.0]            # 1% of the 60000 basis
    bot.cycle()                                    # venue holds it: no re-set
    assert venue.trail_calls == [600.0]


# --- M12/M13: reinvest and the venue-anchored cooldown -----------------------

def _histfills(*rows):
    out = []
    for t, side, price, qty, fee, link in rows:
        out.append({'time_ms': t, 'side': side, 'price': price, 'qty': qty,
                    'fee': fee, 'link_id': link, 'symbol': 'BTCUSDT',
                    'exec_id': f'h{t}'})
    return out


def spec_M13_cooldown_anchors_to_the_venue_TP_fill():
    venue, lines = FakeVenue(), []
    clock = {'t': 1_000_000.0}
    bot = Bot(_cfg(repeat=True, repeat_cooldown_seconds=300.0), ADAPTER,
              venue, Notifier(sink=lines.append), gen_seed=1,
              clock=lambda: clock['t'])
    link = f'{bot.botid}-0-x'
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (999_900_000, 'sell', 60600.0, 0.016, 0.1, link))   # TP filled t=999900
    bot._last_pos = 0.016                          # a round just closed
    assert bot.cycle() == {'round': 'cooling'}     # 999900+300 > 1000000? no...
    clock['t'] = 999_900.0 + 299.0
    bot._last_pos = 0.016
    bot._cool_until = None
    assert bot.cycle() == {'round': 'cooling'}
    clock['t'] = 999_900.0 + 301.0
    bot._last_pos = 0.016
    bot._cool_until = None
    r = bot.cycle()
    assert r == {'round_started': 2} or 'round_started' in r


def spec_M12_reinvest_scales_the_base_from_lifetime_fills():
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    import time as _t
    link = f'{bot.botid}-1-x'
    now_ms = int(_t.time() * 1000)
    # one closed round INSIDE the 30d window: bought 0.1 @ 50000, sold 0.1 @
    # 51000 -> +100 net on capital 1000 -> factor 1.1
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now_ms - 2_000, 'buy', 50000.0, 0.1, 0.0, link),
        (now_ms - 1_000, 'sell', 51000.0, 0.1, 0.0, link))
    bot.cycle()                                    # opens round 1, scaled
    qty = float(venue.position['size'])
    base = 1000.0 / 60000.0                        # unscaled base qty
    assert abs(qty - ADAPTER.round_qty(base * 1.1)) < 1e-9
    assert abs(bot._scale - 1.1) < 1e-9            # lazy-derived, silently —
    # the ship event belongs to round COMPLETIONS (H4a: once per round)


def spec_M12_the_factor_caps_at_the_watchdog_headroom():
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    link = f'{bot.botid}-1-x'
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (1_000, 'buy', 50000.0, 0.1, 0.0, link),
        (2_000, 'sell', 60000.0, 0.1, 0.0, link))  # +1000 on 1000 = x2 raw
    fills = bot._own_fills()
    assert bot._reinvest_scale(fills) == 1.2       # capped (F2 headroom)


def spec_M12_losses_shrink_never_grow():
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    link = f'{bot.botid}-1-x'
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (1_000, 'buy', 50000.0, 0.1, 0.0, link),
        (2_000, 'sell', 48000.0, 0.1, 0.0, link))  # -200 on 1000
    assert abs(bot._reinvest_scale(bot._own_fills()) - 0.8) < 1e-9


def spec_M10_a_passed_tranche_is_done_the_rest_renormalise():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                    # base fills at 60000
    venue.mark = 60800.0                           # past t1, before t2
    venue.position = dict(venue.position, size='0.008')   # t1 fired: half gone
    bot.cycle()
    tps = [o for o in venue.stop_orders('linear', 'BTCUSDT')
           if 'TakeProfit' in o['stopOrderType']]
    assert len(tps) == 1                           # t1 is NOT re-placed
    assert float(tps[0]['triggerPrice']) == 61200.0
    assert tps[0]['qty'] == '0.008'                # whole remainder, renormalised


def spec_M10_blown_through_closes_at_target_or_better():
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    venue.mark = 62000.0                           # past BOTH targets
    r = bot.cycle()
    assert r == {'round': 'closing'}               # M3: never without an exit
    sells = [o for o in venue.orders
             if o['side'] == 'Sell' and o['reduce_only']]
    assert sells and sells[-1]['price'] == 61200.0     # deepest target, or better
    assert any('every tranche target met' in ln for ln in lines)


# --- the 2026-08-06 audit: the three martingale HIGHs, pinned --------------

def spec_M12_a_total_loss_refuses_the_next_round():
    """0.0 is a real factor, not 'unset' — truthiness re-entered at FULL
    size after the capital was gone (audit H1)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True, reinvest=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    link = f'{bot.botid}-1-x'
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: _histfills(
        (now - 2000, 'buy', 60000.0, 1.0, 0.0, link),
        (now - 1000, 'sell', 59000.0, 1.0, 0.0, link))   # -1000 on capital 1000
    assert bot._reinvest_scale(bot._own_fills()) == 0.0
    assert bot.cycle() == {'round': 'capital_exhausted'}
    assert venue.position is None                        # nothing opened
    assert any('consumed the capital' in ln for ln in lines)


def spec_M10_a_fired_tranche_stays_fired_when_mark_retreats():
    """'Passed' is monotone within a round — measured against the best mark
    the round has seen (audit H2)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()                                    # base at 60000
    venue.mark = 60800.0                           # t1 (+1%) passed
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    venue.mark = 60300.0                           # price RETREATS below t1
    bot.cycle()
    book = venue.stop_orders('linear', 'BTCUSDT')
    tps = [o for o in book if 'TakeProfit' in o['stopOrderType']]
    assert len(tps) == 1                           # t1 does NOT resurrect
    assert float(tps[0]['triggerPrice']) == 61200.0


def spec_M14_a_liquidated_round_stands_down_instead_of_re_entering():
    """A forced close is not a completed round (audit H3)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_cfg(repeat=True), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                    # round 1 opens
    bot.cycle()
    import time as _t
    now = int(_t.time() * 1000)
    venue.fills_history = lambda mt, sym, a, b: [
        {'time_ms': now - 500, 'side': 'sell', 'price': 54000.0, 'qty': 0.016,
         'fee': 0.0, 'link_id': '', 'symbol': 'BTCUSDT', 'exec_id': 'liq',
         'market_type': 'linear', 'venue_closed': True,
         'venue_kind': 'liquidation'}]
    venue.position = None                          # wiped out
    r = bot.cycle()
    assert r == {'round': 'liquidation'}
    assert not bot.alive                           # D1: stands down
    assert not venue.position                      # never re-entered


def spec_M15_the_round_anchor_is_recovered_from_the_venue():
    """A restart mid-round must not re-anchor on the average entry: that
    deepens every remaining rung AND un-suppresses rungs that already
    filled, pushing past the validated capital (audit 2026-08-06)."""
    from gridgremlin.ladder import anchor_from_rung
    cfg = _cfg()
    anchor = 60000.0
    from gridgremlin.ladder import martingale_schedule
    _, cumdev = martingale_schedule(cfg)[1]
    resting = anchor * (1.0 - cumdev)                  # rung 1's true price
    assert abs(anchor_from_rung(cfg, resting, 1) - anchor) < 1e-6
    assert anchor_from_rung(cfg, resting, 0) is None   # rung 0 is the exit
    venue, lines = FakeVenue(), []
    bot = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                        # base
    bot.cycle()                                        # ladder rests
    fresh = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=2)
    fresh._last_pos = float(venue.position['size'])
    fresh.cycle()                                      # the restart
    assert fresh._anchor is not None
    assert abs(fresh._anchor - 60000.0) < 1.0          # recovered, not guessed
    assert any('anchor recovered' in ln for ln in lines)


def spec_M11_trailing_waits_for_the_first_tranche():
    """A trail tighter than the first tranche closed rounds before they
    could take profit — 30 live rounds averaging a small loss (2026-08-06)."""
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(trailing_stop_pct=0.008), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                   # base at 60000
    bot.cycle()                                   # tranches rest
    assert not getattr(venue, 'trail_calls', [])  # NOT armed yet
    venue.mark = 60800.0                          # t1 (+1%) fires
    venue.position = dict(venue.position, size='0.008')
    bot.cycle()
    assert venue.trail_calls                      # now it rides


def spec_M10_a_tranche_must_clear_the_mark_by_the_guard_band():
    """Between our read and the venue's write the mark moves; a target that
    merely exceeds mark gets refused ('should be higher than base_price').
    B3's law applied to the hosted TP (live refusal, 2026-08-06)."""
    from gridgremlin.ladder import guard_band
    venue, lines = FakeVenue(), []
    bot = Bot(_tranche_cfg(), ADAPTER, venue, Notifier(sink=lines.append),
              gen_seed=1)
    bot.cycle()
    guard = guard_band(venue.mark - 0.5, venue.mark + 0.5)
    basis = 60000.0
    # a target a hair above mark is NOT placeable; the same target with room is
    near = bot._round_targets(basis, 0.016, mark=60599.0, guard=guard)
    assert all(p > 60599.0 + guard for p, _ in near)
    assert not any(abs(p - 60600.0) < 1e-9 for p, _ in near)   # t1 excluded
    fresh = Bot(_tranche_cfg(), ADAPTER, FakeVenue(),
                Notifier(sink=lines.append), gen_seed=2)
    far = fresh._round_targets(basis, 0.016, mark=60000.0, guard=guard)
    assert any(abs(p - 60600.0) < 1e-9 for p, _ in far)        # room: t1 fine
    # and the high-water still persists across calls (M10): once passed, gone
    bot._round_targets(basis, 0.016, mark=60599.0, guard=guard)
    again = bot._round_targets(basis, 0.016, mark=60000.0, guard=guard)
    assert not any(abs(p - 60600.0) < 1e-9 for p, _ in again)
