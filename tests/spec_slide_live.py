# Specs for the slide's live wiring (D28, PR B): X8 the stop follows the
# window, G21 confirmation, G22 the persisted offset, G17 live overlap and
# negative links, I3 sized for the widest window, T6 confirmation in bars,
# and the ops readouts (snapshot, range review).

import importlib.util
import json
import tempfile
from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.apply import check_link_fits, rung_of, widest_rung
from gridgremlin.backtest import backtest
from gridgremlin.bot import Bot
from gridgremlin.config import (ConfigError, slide_leverage_warning,
                                validate_config)
from gridgremlin.events import Notifier
from gridgremlin.ladder import stop_level_for
from gridgremlin.slide_state import SlideState, SlideStateError

from spec_loop import FakeVenue

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})
SLIDE = {'trigger_rungs': 2, 'max_rungs': 100, 'confirm_seconds': 0}
STOP = {'watch': 'mark_price', 'rungs_beyond': 3}


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed',
           'slide': dict(SLIDE), 'stop': dict(STOP)}
    row.update(over)
    return validate_config(row)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _bot(venue, lines, clock=None, state=None, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1, clock=clock, slide_state=state)


def _holding(venue, size='0.021', avg='63000'):
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': size,
                      'avgPrice': avg, 'leverage': '10', 'unrealisedPnl': '0'}


def _tmp():
    return Path(tempfile.mkdtemp()) / 'slide_state.json'


def _bar(o, h, l, c):
    return {'o': o, 'h': h, 'l': l, 'c': c}


# --- X8: the stop follows the window -----------------------------------------

def spec_X8_a_slide_bot_gives_rungs_beyond_never_an_absolute_level():
    for bad, text in (({'watch': 'mark_price', 'level': 48000}, 'rungs_beyond'),
                      ({'watch': 'mark_price'}, 'required'),
                      ({'watch': 'mark_price', 'rungs_beyond': 0}, '>= 1'),
                      ({'watch': 'mark_price', 'rungs_beyond': 1.5}, 'integer')):
        try:
            _cfg(stop=bad)
        except ConfigError as e:
            assert text in str(e), (bad, str(e))
        else:
            raise AssertionError(f'accepted {bad!r}')
    try:
        _cfg(slide=None, stop={'watch': 'mark_price', 'rungs_beyond': 3})
    except ConfigError as e:
        assert "without 'slide'" in str(e)
    else:
        raise AssertionError('rungs_beyond accepted without slide')
    assert _cfg()['stop'] == {'watch': 'mark_price', 'rungs_beyond': 3,
                              'server_side': False}
    # the account-equity watch stays absolute: a wallet has no window
    cfg = _cfg(stop={'watch': 'account_equity', 'level': 2500})
    assert cfg['stop']['level'] == 2500.0


def spec_X8_the_stop_level_sits_rungs_beyond_the_window_near_edge():
    cfg = _cfg()                                    # step 1000, home 50000..70000
    assert stop_level_for(cfg, 0) == 47000.0
    assert stop_level_for(cfg, 12) == 59000.0       # follows the window
    short = _cfg(side='short')
    assert stop_level_for(short, 0) == 73000.0
    assert stop_level_for(short, -5) == 68000.0
    fixed = _cfg(slide=None, stop={'watch': 'mark_price', 'level': 48000})
    assert stop_level_for(fixed, 0) == 48000.0      # an absolute level is itself
    assert stop_level_for(_cfg(stop=None), 7) is None


def spec_X8_after_a_slide_the_stop_fires_where_home_would_not():
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines)
    bot.cycle()
    venue.mark = 72000.0                            # K=2 rungs past the top
    bot.cycle()
    assert bot.offset == 12 and bot.alive
    venue.mark = 58000.0     # above home's 47000 — below the window's 59000
    bot.cycle()
    assert not bot.alive
    assert any('kill' in ln and '59000' in ln
               and 'rungs beyond the window at +12' in ln for ln in lines)


def spec_X8_a_server_side_stop_is_re_set_after_a_slide():
    venue, lines = FakeVenue(mark=60000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop=dict(STOP, server_side=True))
    bot.cycle()
    assert venue.sl_calls[-1][0] == 47000.0
    venue.mark = 72000.0
    bot.cycle()                                     # the window moves
    assert bot.offset == 12
    bot.cycle()                                     # X3 is level-triggered
    assert venue.sl_calls[-1][0] == 59000.0         # the venue's stop followed


# --- G21: confirmation ---------------------------------------------------------

def spec_G21_a_wick_past_the_trigger_never_moves_a_confirmed_window():
    clock = Clock()
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, clock=clock, slide=dict(SLIDE, confirm_seconds=60))
    bot.cycle()
    venue.mark = 72000.0
    clock.t += 1
    bot.cycle()                                     # arms the clock
    assert bot.offset == 0
    assert any('confirming for 60s' in ln for ln in lines)
    clock.t += 30
    bot.cycle()
    assert bot.offset == 0                          # 30s: not yet
    venue.mark = 69000.0                            # the wick reverses
    clock.t += 10
    bot.cycle()
    assert bot.offset == 0                          # and the clock resets
    venue.mark = 72000.0
    clock.t += 10
    bot.cycle()                                     # re-arms
    clock.t += 50
    bot.cycle()
    assert bot.offset == 0                          # 50s held: not yet
    clock.t += 15
    bot.cycle()
    assert bot.offset == 12                         # 65s held: slides
    assert any('window +0 -> +12' in ln for ln in lines)


def spec_G21_sabotage_zero_confirmation_slides_on_the_first_read():
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines)                        # confirm_seconds 0
    bot.cycle()
    venue.mark = 72000.0
    bot.cycle()
    assert bot.offset == 12                         # the wick moved the house


# --- G17 live: the overlap keeps its orders; a short's links go negative -----

def spec_G17_live_the_overlap_keeps_its_orders_only_the_edges_move():
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, place_within_pct=0.5,
               slide=dict(SLIDE, trigger_rungs=1, ref_position=1.0))
    bot.cycle()
    home = {o['order_id'] for o in venue.orders}
    assert len(home) == 10                          # buys 50000..59000
    venue.mark = 71000.0                            # one rung past the top
    counts = bot.cycle()
    assert bot.offset == 1
    assert counts['cancels'] == 1 and counts['creates'] == 11
    now = {o['order_id'] for o in venue.orders}
    assert len(home & now) == 9                     # rungs 1..9 never moved
    assert {rung_of(o['link_id'], bot.botid) for o in venue.orders} \
        == set(range(1, 21))


def spec_G17_live_a_short_slides_down_with_negative_links():
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, side='short')
    bot.cycle()
    venue.mark = 48000.0                            # 2 rungs below the bottom
    bot.cycle()
    assert bot.offset == -12
    rungs = {rung_of(o['link_id'], bot.botid) for o in venue.orders}
    assert rungs and min(rungs) < 0
    for o in venue.orders:                          # the link round-trips
        assert o['link_id'].startswith(
            f"{bot.botid}-{rung_of(o['link_id'], bot.botid)}-")


# --- G22: the persisted offset -----------------------------------------------

def spec_G22_the_offset_is_durable_BEFORE_the_orders_move():
    order = []

    class Sequenced(FakeVenue):
        def place_order(self, *a, **kw):
            order.append('place')
            return super().place_order(*a, **kw)

        def cancel_order(self, *a, **kw):
            order.append('cancel')
            return super().cancel_order(*a, **kw)

    class Watching(SlideState):
        def set(self, botid, offset):
            order.append('state')
            super().set(botid, offset)

    tmp = _tmp()
    venue, lines = Sequenced(mark=60000.0), []
    bot = _bot(venue, lines, state=Watching(tmp))
    bot.cycle()
    del order[:]
    venue.mark = 72000.0
    bot.cycle()
    assert order[0] == 'state' and 'cancel' in order and 'place' in order
    assert SlideState(tmp).get(bot.botid) == 12      # a new process reads it
    assert json.loads(tmp.read_text()) == {bot.botid: 12}


def spec_G22_a_restart_resumes_at_the_window_with_zero_churn():
    tmp = _tmp()
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, state=SlideState(tmp))
    bot.cycle()
    venue.mark = 72000.0
    bot.cycle()
    n = len(venue.orders)
    fresh = _bot(venue, lines, state=SlideState(tmp))   # a new process
    assert fresh.offset == 12
    counts = fresh.cycle()
    assert (counts['amends'], counts['cancels'], counts['creates']) == (0, 0, 0)
    assert len(venue.orders) == n


def spec_G22_missing_state_means_home_a_lost_ratchet_never_lost_money():
    tmp = _tmp()
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, state=SlideState(tmp))
    bot.cycle()
    venue.mark = 72000.0
    bot.cycle()
    assert any(rung_of(o['link_id'], bot.botid) > 20 for o in venue.orders)
    venue.mark = 60000.0          # back inside home; the old bot would hold +12
    fresh = _bot(venue, lines, state=None)          # no file: home
    assert fresh.offset == 0
    counts = fresh.cycle()
    # the slid window's buys sit ABOVE the ref now — marketable, so they go
    assert counts['cancels'] == 3 and counts['creates'] == 3
    assert all(0 <= rung_of(o['link_id'], fresh.botid) <= 9
               for o in venue.orders)
    # (with the market still past the trigger, a fresh bot simply ratchets
    # back to the same window on its first cycle and keeps every order)


def spec_G22_a_corrupt_state_file_refuses_never_guesses():
    tmp = _tmp()
    tmp.write_text('{not json')
    try:
        SlideState(tmp)
    except SlideStateError as e:
        assert 'deliberately' in str(e)
    else:
        raise AssertionError('a corrupt slide state was swallowed')
    tmp.write_text('{"x": 1.5}')
    try:
        SlideState(tmp)
    except SlideStateError as e:
        assert 'integers' in str(e)
    else:
        raise AssertionError('a malformed offset was accepted')


def spec_G22_a_failed_state_write_never_blocks_the_slide():
    class BrokenDisk:
        def get(self, botid):
            return 0

        def set(self, botid, offset):
            raise OSError(30, 'Read-only file system')

    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, state=BrokenDisk())
    bot.cycle()
    venue.mark = 72000.0
    bot.cycle()
    assert bot.offset == 12                         # the slide STILL happened
    assert any('slide state write FAILED' in ln for ln in lines)


def spec_G22_a_persisted_offset_is_clamped_to_the_config_on_restart():
    tmp = _tmp()
    SlideState(tmp).set('linBTCUSDTl', 40)
    venue, lines = FakeVenue(mark=60000.0), []
    bot = _bot(venue, lines, state=SlideState(tmp), slide=dict(SLIDE, max_rungs=8))
    assert bot.offset == 8                          # G19 holds on restart
    assert any('outside this config' in ln for ln in lines)
    # the key removed: home, and the file is not consulted
    plain = _bot(venue, lines, state=SlideState(tmp), slide=None, stop=None)
    assert plain.offset == 0


# --- I3: the link fits the furthest window -----------------------------------

def spec_I3_the_link_is_sized_for_the_furthest_window():
    assert widest_rung(_cfg(slide=None, stop=None)) == 20
    assert widest_rung(_cfg()) == 120
    assert widest_rung(_cfg(side='short')) == -100         # '-100': 4 chars
    assert widest_rung(_cfg(side='short',
                            slide=dict(SLIDE, max_rungs=1))) == 20   # '20' > '-1'
    check_link_fits('linBTCUSDTl', widest_rung(_cfg()), venue_limit=36)
    wide = _cfg(slide=dict(SLIDE, max_rungs=10 ** 8))
    try:
        check_link_fits('linBTCUSDTl', widest_rung(wide), venue_limit=26)
    except ConfigError as e:
        assert 'venue limit' in str(e)
    else:
        raise AssertionError('a slide that overflows the link limit was accepted')


# --- leverage sanity: a build warning, not yet a rule -------------------------

def spec_slide_leverage_warning_states_the_replay_evidence():
    assert slide_leverage_warning(_cfg(leverage=10)) is None
    assert slide_leverage_warning(_cfg(slide=None, stop=None, leverage=75)) is None
    msg = slide_leverage_warning(_cfg(leverage=75))
    assert msg and '75x' in msg and 'liquidated' in msg


# --- T6: the replay confirms in whole bars ------------------------------------

def spec_T6_the_replay_confirms_a_slide_in_whole_bars():
    flat, up = _bar(60000.0, 60100.0, 59900.0, 60000.0), _bar(72500.0, 72600.0, 72400.0, 72500.0)
    spike = [flat] * 3 + [up] + [flat] * 3
    assert backtest(_cfg(), ADAPTER, spike, bar_hours=1.0)['slides'] == 1
    hour = dict(SLIDE, confirm_seconds=3600)
    assert backtest(_cfg(slide=hour), ADAPTER, spike, bar_hours=1.0)['slides'] == 0
    held = [flat] * 3 + [up] * 3
    assert backtest(_cfg(slide=hour), ADAPTER, held, bar_hours=1.0)['slides'] == 1
    three = dict(SLIDE, confirm_seconds=10800)
    assert backtest(_cfg(slide=three), ADAPTER, held, bar_hours=1.0)['slides'] == 0


# --- the readouts: snapshot and range review ----------------------------------

def spec_F4_the_snapshot_carries_a_slid_window():
    from gridgremlin.main import snapshot_row

    class Slid:
        botid, alive, _last_pos, offset = 'x', True, 0.0, 12

    class Home:
        botid, alive, _last_pos, offset = 'y', True, 0.0, 0

    row = snapshot_row([Slid(), Home()], {'equity': 1.0, 'mm_rate': 0.0}, 0)
    assert row['bots']['x']['offset'] == 12
    assert 'offset' not in row['bots']['y']


def spec_range_review_reports_the_slid_window():
    path = Path(__file__).resolve().parent.parent / 'ops' / 'range_review.py'
    spec = importlib.util.spec_from_file_location('range_review', path)
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    raw = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'lower': 50000, 'upper': 70000, 'rungs': 21, 'spacing_type': 'fixed'}
    assert 'IDLE ABOVE' in rr.review_row(raw, 72000.0)
    slid = rr.review_row(raw, 72000.0, offset=12)
    assert '62000..82000' in slid and 'slid +12 rungs' in slid and 'IDLE' not in slid
    assert 'slid +12' in rr.review_row(dict(raw, spacing_type='percent'),
                                        72000.0, offset=12)
    d = Path(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    (d / 'logs' / 'slide_state.json').write_text('{"linBTCUSDTl": 12}')
    assert rr.slide_offsets(d / 'configs' / 'fleet.json', {}) == {'linBTCUSDTl': 12}
    assert rr.slide_offsets(d / 'configs' / 'fleet.json',
                            {'slide_state': str(d / 'nope.json')}) == {}
