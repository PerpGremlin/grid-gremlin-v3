# Specs for SPEC B3-B7 and G13's placer half. Every guard's incident is here,
# and every guard is proven LOAD-BEARING by disabling it (T1).

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import BACKOFF_BASE, FLAP_LIMIT, Bot
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier
from gridgremlin.exchange.errors import VenueError
from gridgremlin.ladder import grid_rungs, placeable_exits, split

from spec_loop import FakeVenue

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _bot(venue, lines, clock=None, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1, clock=clock or Clock())


# --- B3 / G13 placer half: the cross guard -----------------------------------

def spec_B3_crossing_creates_are_skipped():
    venue, lines = FakeVenue(mark=60000.0), []
    venue.tickers = lambda c, s: {'markPrice': '60000',
                                  'bid1Price': '58900',    # spread swallows
                                  'ask1Price': '60000',    # the 59k rung
                                  'fundingRate': '0', 'nextFundingTime': '0'}
    bot = _bot(venue, lines)
    bot.cycle()
    placed = {o['price'] for o in venue.orders}
    assert 59000.0 not in placed                      # inside the guard band
    assert 58000.0 in placed
    assert any(' skip ' in ln for ln in lines)


def spec_B3_sabotage_without_the_guard_the_cross_submits():
    venue, lines = FakeVenue(mark=60000.0), []
    venue.tickers = lambda c, s: {'markPrice': '60000', 'bid1Price': '58900',
                                  'ask1Price': '60000', 'fundingRate': '0',
                                  'nextFundingTime': '0'}
    bot = _bot(venue, lines)
    bot._would_cross = lambda *a: False               # guard removed
    bot.cycle()
    assert 59000.0 in {o['price'] for o in venue.orders}   # would taker-fill live


def spec_B3_one_band_definition():
    import inspect
    import gridgremlin.bot as botmod
    src = inspect.getsource(botmod)
    assert 'guard_band' in src and 'CROSS_GUARD_BPS' not in src   # imported, not re-derived


# --- B4: the resting-exit exemption ------------------------------------------

def spec_B4_in_band_exit_drops_unless_resting():
    rungs = grid_rungs(_cfg(), ADAPTER)
    exits = split('long', rungs, 60000.0, basis=55000.0)['exits']
    bid, ask = 60000.0, 61200.0                       # band swallows the 61k rung
    dropped = placeable_exits('long', exits, bid, ask, frozenset())
    assert 61000.0 not in {p for _, p in dropped}
    kept = placeable_exits('long', exits, bid, ask, frozenset({11}))  # 61k rests
    assert 61000.0 in {p for _, p in kept}            # exemption, keyed by rung


def spec_B4_sabotage_no_exemption_cancels_the_resting_exit():
    # the 2026-07-30 incident: the only sell above spot vanished 68% of the
    # time. With the exemption removed, the plan drops the resting rung and
    # the diff cancels a live exit for being near the book.
    from gridgremlin.apply import diff, make_link
    from gridgremlin.ladder import plan_grid
    cfg = _cfg()
    resting = [{'order_id': 'o1', 'link_id': make_link('linBTCUSDTl', 11, 1),
                'side': 'Sell', 'price': 61000.0, 'qty': 0.007,
                'cum_exec_qty': 0.0, 'reduce_only': True, 'status': 'New',
                'position_idx': 1, 'order_type': 'Limit', 'updated_time_ms': 0}]
    held, basis, bid, ask = 0.007, 55000.0, 60000.0, 61200.0
    with_exemption = plan_grid(cfg, ADAPTER, 60000.0, held, basis, bid, ask,
                               frozenset({11}))
    cancel, _ = diff(with_exemption, resting, 'linBTCUSDTl')
    assert cancel == []                               # exempt: left alone
    without = plan_grid(cfg, ADAPTER, 60000.0, held, basis, bid, ask,
                        frozenset())
    cancel, _ = diff(without, resting, 'linBTCUSDTl')
    assert cancel                                     # the incident, resurrected


# --- B5: the flap cooldown ---------------------------------------------------

class LossyVenue(FakeVenue):
    """Accepts placements and loses them — the book race, permanently."""

    def place_order(self, *a, **k):
        pass


def spec_B5_flapping_rung_cools_after_the_limit():
    venue, lines, clock = LossyVenue(), [], Clock()
    bot = _bot(venue, lines, clock)
    for _ in range(FLAP_LIMIT + 1):
        bot.cycle()
        clock.t += 5
    assert any('flapping' in ln for ln in lines)
    counts = bot.cycle()
    assert counts['creates'] == 0                     # everything cooling
    assert all(cause == 'flap' for _, cause in bot._cooldown.values())   # B6


def spec_B5_a_trading_rung_is_never_cooled():
    # the actively-trading-rung bug: position moved -> not a flap
    venue, lines, clock = LossyVenue(), [], Clock()
    bot = _bot(venue, lines, clock)
    sizes = iter([0.0, 0.001, 0.002, 0.003, 0.004, 0.005])
    for _ in range(FLAP_LIMIT + 2):
        venue.position = {'positionIdx': 1, 'side': 'Buy',
                          'size': str(next(sizes)), 'avgPrice': '59000',
                          'leverage': '10', 'unrealisedPnl': '0'}
        bot.cycle()
        clock.t += 5
    assert not any('flapping' in ln for ln in lines)
    assert bot._cooldown == {}


def spec_B5_sabotage_without_the_guard_the_race_never_ends():
    venue, lines, clock = LossyVenue(), [], Clock()
    bot = _bot(venue, lines, clock)
    bot._account_flaps = lambda *a: None              # guard removed
    for _ in range(FLAP_LIMIT + 3):
        bot.cycle()
        clock.t += 5
    last = bot.cycle()
    assert last['creates'] > 0                        # still re-placing forever


# --- B7: the margin backoff --------------------------------------------------

class BrokeVenue(FakeVenue):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def place_order(self, *a, **k):
        self.attempts += 1
        raise VenueError('insufficient margin', kind='margin')


def spec_B7_margin_halts_growth_with_doubling_backoff():
    venue, lines, clock = BrokeVenue(), [], Clock()
    bot = _bot(venue, lines, clock)
    bot.cycle()
    assert venue.attempts == 1                        # first failure stops the batch
    assert bot._backoff == BACKOFF_BASE
    first_until = bot._backoff_until
    counts = bot.cycle()                              # still inside the window
    assert counts['creates'] == 0 and venue.attempts == 1
    clock.t = first_until + 1                         # window expires -> retry
    bot.cycle()
    assert venue.attempts == 2 and bot._backoff == BACKOFF_BASE * 2


def spec_B7_cancels_still_run_during_backoff():
    venue, lines, clock = BrokeVenue(), [], Clock()
    stale = {'order_id': 'stale', 'link_id': 'linBTCUSDTl-40-1',
             'side': 'Buy', 'price': 69000.0, 'qty': '0.001',
             'reduce_only': False, 'position_idx': 1}
    bot = _bot(venue, lines, clock)
    bot.cycle()                                       # enters backoff
    venue.orders.append(stale)                        # a rung the plan never wants
    bot.cycle()
    assert 'stale' not in {o['order_id'] for o in venue.orders}   # B7: shrink allowed


def spec_B7_backoff_event_is_anti_spammed():
    venue, lines, clock = BrokeVenue(), [], Clock()
    bot = _bot(venue, lines, clock)
    for _ in range(7):                                # 30..240, then parked at 300
        bot.cycle()
        clock.t = bot._backoff_until + 1
    backoffs = [ln for ln in lines if ' backoff ' in ln]
    margins = [ln for ln in lines if ' margin ' in ln]
    assert len(margins) == 7
    assert len(backoffs) == 5                         # silent once at the ceiling
