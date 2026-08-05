# Specs for SPEC S1-S8 — the start matrix, one spec per non-collapsing cell.
# Adopt cells (in-profit, underwater, over-cap, floored) live in spec_plan.py;
# this file holds flat, seed, restart, involuntary flat, and the reset list.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier
from gridgremlin.ladder import plan_grid

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


def _bot(venue, lines, **over):
    return Bot(_cfg(**over), ADAPTER, venue, Notifier(sink=lines.append),
               gen_seed=1)


class SeedVenue(FakeVenue):
    def __init__(self, mark=60000.0):
        super().__init__(mark)
        self.market_orders = []

    def place_market(self, category, symbol, side, qty, position_idx=0,
                     reduce_only=False, link_id=None, borrow=False):
        self.market_orders.append((side, float(qty)))
        self.market_links = getattr(self, 'market_links', [])
        self.market_links.append(link_id)
        self.position = {'positionIdx': 1, 'side': side, 'size': qty,
                         'avgPrice': str(self.mark), 'leverage': '10',
                         'unrealisedPnl': '0'}


# --- S1: flat — basis-anchored mechanisms are inert by construction ----------

def spec_S1_flat_plan_is_identical_for_any_basis():
    cfg = _cfg()
    a = plan_grid(cfg, ADAPTER, 60000.0, 0.0, None)
    b = plan_grid(cfg, ADAPTER, 60000.0, 0.0, 55000.0)
    c = plan_grid(cfg, ADAPTER, 60000.0, 0.0, 65000.0)
    assert a == b == c


# --- the flat row of the matrix: mark inside / above / below the range -------

def spec_S8_flat_mark_inside_arms_the_entry_side():
    orders = plan_grid(_cfg(), ADAPTER, 60000.0)
    assert len(orders) == 10 and all(o['side'] == 'Buy' for o in orders)


def spec_S8_flat_mark_below_the_range_rests_nothing():
    assert plan_grid(_cfg(), ADAPTER, 45000.0) == []      # idles empty (G11)


def spec_S8_flat_mark_above_the_range_arms_everything_cap_bounded():
    orders = plan_grid(_cfg(), ADAPTER, 75000.0)
    assert len(orders) == 21 and all(o['side'] == 'Buy' for o in orders)


# --- S2/S3: seed -------------------------------------------------------------

def spec_S3_seed_is_one_lot_per_exit_rung_at_market():
    venue, lines = SeedVenue(), []
    bot = _bot(venue, lines, seed=True)
    result = bot.cycle()
    assert result == {'seeded': True}
    side, qty = venue.market_orders[0]
    assert side == 'Buy'
    assert abs(qty - 10 * 0.007) < 1e-9        # 10 exit-side rungs, ref-priced lot
    assert any('[ship] seed' in ln for ln in lines)


def spec_S3_seed_scales_with_where_the_mark_sits():
    low, high = SeedVenue(mark=62000.0), SeedVenue(mark=68000.0)
    _bot(low, [], seed=True).cycle()
    _bot(high, [], seed=True).cycle()
    assert low.market_orders[0][1] > high.market_orders[0][1]   # more room, more seed


def spec_S3_next_cycle_covers_the_seed():
    venue, lines = SeedVenue(), []
    bot = _bot(venue, lines, seed=True)
    bot.cycle()                                # seeds
    counts = bot.cycle()                       # plans over the seeded position
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    assert [float(o['qty']) for o in sells] == [0.007, 0.007, 0.007]   # windowed
    assert counts['desired'] == 10             # full coverage is intent (W1)


def spec_S2_a_position_means_the_seed_already_happened():
    venue, lines = SeedVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.070',
                      'avgPrice': '60000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines, seed=True)
    bot.cycle()
    assert venue.market_orders == []           # restart: never re-fires


def spec_S2_resting_owned_orders_also_mean_no_seed():
    venue, lines = SeedVenue(), []
    plain = _bot(venue, lines)
    plain.cycle()                              # a running grid's entries rest
    seeded = _bot(venue, lines, seed=True)     # "restart" with the toggle on
    seeded.cycle()
    assert venue.market_orders == []


def spec_S1_seeded_at_mark_the_adoption_family_is_inert():
    # basis == mark after the seed: the suppressed prefix equals the seeded
    # lots and dissolves as exits fill — no band, no special case (D6/D9)
    venue, lines = SeedVenue(), []
    bot = _bot(venue, lines, seed=True)
    bot.cycle()
    bot.cycle()
    buys = sorted((o['price'] for o in venue.orders if o['side'] == 'Buy'),
                  reverse=True)
    assert buys == []                          # 10 lots seeded = 10 suppressed


# --- S6: restart — re-adoption and the reset list ----------------------------

def spec_S6_restart_readopts_with_zero_churn():
    venue, lines = FakeVenue(), []
    _bot(venue, lines).cycle()
    n = len(venue.orders)
    fresh = _bot(venue, lines)                 # a new process, same config
    counts = fresh.cycle()
    assert (counts['amends'], counts['cancels'], counts['creates']) == (0, 0, 0)
    assert len(venue.orders) == n


def spec_S6_the_reset_list_is_complete_and_documented():
    bot = _bot(FakeVenue(), [])
    documented = {'_last_pos', '_gen', '_held_ref', '_placed_last', '_flap',
                  '_cooldown', '_backoff', '_backoff_until', '_backoff_emitted',
                  '_exit_links_last', '_uncovered_warned', '_anomaly_warned',
                  '_anchor', '_round'}
    state = {k for k, v in vars(bot).items()
             if k.startswith('_') and not callable(v)
             and k not in ('_now', '_entry_side', '_exit_side', '_min_gap',
                           '_borrow')}
    assert state == documented, state ^ documented


# --- S4: a position the bot cannot explain halts and alerts ------------------

def spec_S4_wrong_side_position_halts_the_bot():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Sell', 'size': '0.5',
                      'avgPrice': '60000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines)
    assert bot.cycle() == {'anomaly': True}
    assert venue.orders == []                  # nothing placed
    bot.cycle()
    assert sum('WRONG side' in ln for ln in lines) == 1    # warned once


# --- S5: basis beyond the range ----------------------------------------------

def spec_S5_basis_beyond_range_no_exits_one_warning():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.021',
                      'avgPrice': '71000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines)
    bot.cycle()
    bot.cycle()
    assert not any(o['side'] == 'Sell' for o in venue.orders)
    assert sum('nothing harvestable' in ln for ln in lines) == 1


# --- S7: involuntary flat is terminal ----------------------------------------

def spec_S7_external_close_kills_cancels_and_states_the_residue():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.021',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines)
    bot.cycle()                                # exits + entries rest
    assert venue.orders
    venue.position = None                      # a stop or manual close: no
    assert bot.cycle() is None                 # owned exit disappeared
    assert bot.alive is False
    assert venue.orders == []                  # X5: owned orders cancelled
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'nothing owned rests' in kill       # X4: residue stated


def spec_S7_our_own_exit_filling_is_not_a_kill():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.007',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines)
    bot.cycle()
    sell = next(o for o in venue.orders if o['side'] == 'Sell')
    venue.orders = [o for o in venue.orders if o is not sell]   # exit FILLED
    venue.position = None                       # position went to zero with it
    bot.cycle()
    assert bot.alive is True                    # a sell-out, not an execution
    assert any(' exit ' in ln for ln in lines)


# --- I5: the seed order carries our identity ---------------------------------

def spec_I5_the_seed_order_carries_an_owned_link():
    from gridgremlin.apply import rung_of
    venue, lines = SeedVenue(), []
    bot = _bot(venue, lines, seed=True)
    assert bot.cycle() == {'seeded': True}
    assert rung_of(venue.market_links[0], bot.botid) == 0


# --- V6/G6: the config basis is a fallback — a venue-reported basis wins -----
# v2's lesson: demo/spot venues may keep no basis; that is WHY the config
# field exists. Where the venue does report one, truth overrules the config.

class SpotVenue(FakeVenue):
    holding = 10.0
    basis_reported = None          # a venue that DOES report basis, for B

    def read_symbol_truth(self, market_type, symbol, funding_interval=480.0):
        from gridgremlin.exchange.bybit.truth import read_symbol_truth
        t = read_symbol_truth(self, market_type, symbol, funding_interval,
                              base_coin='LTC')
        if self.basis_reported is not None and t['positions']:
            t['positions'][0]['avg_entry'] = self.basis_reported
        return t

    def wallet_balance(self):
        return {'list': [{'totalEquity': '1000', 'coin': [
            {'coin': 'LTC', 'walletBalance': str(self.holding),
             'equity': '440', 'availableToWithdraw': str(self.holding)}]}]}


SPOT_ADAPTER = None


def _spot_bot(venue, lines, **over):
    from gridgremlin.adapters import SpotAdapter
    adapter = SpotAdapter({'symbol': 'LTCUSDT', 'qty_step': 0.00001,
                           'price_tick': 0.01, 'min_qty': 0.00001,
                           'min_notional': 5.0, 'settle_coin': 'USDT'})
    row = {'market_type': 'spot', 'symbol': 'LTCUSDT', 'side': 'long',
           'capital': 3000.0, 'upper': 52.0, 'lower': 36.0, 'rungs': 17,
           'place_within_pct': 0.2}
    row.update(over)
    return Bot(validate_config(row), adapter, venue,
               Notifier(sink=lines.append), gen_seed=1)


def spec_V6_venue_keeps_no_basis_the_config_field_serves():
    venue = SpotVenue(mark=44.0)
    bot = _spot_bot(venue, [], assumed_avg_entry=48.0)
    bot.cycle()
    sells = [o['price'] for o in venue.orders if o['side'] == 'Sell']
    assert sells and all(p >= 48.0 * 1.001 for p in sells)   # config floor holds


def spec_V6_a_venue_reported_basis_overrules_the_config():
    venue = SpotVenue(mark=44.0)
    venue.basis_reported = 40.0
    bot = _spot_bot(venue, [], assumed_avg_entry=48.0)
    bot.cycle()
    sells = [o['price'] for o in venue.orders if o['side'] == 'Sell']
    assert sells and min(sells) < 48.0             # truth won, config ignored


# --- D24: a borrow bot marks every placement -----------------------------------

def spec_D24_placements_carry_the_borrow_flag():
    class Recorder(SpotVenue):
        def __init__(self, mark=44.0):
            super().__init__(mark)
            self.borrows = []

        def place_order(self, category, symbol, side, qty, price, link_id,
                        position_idx=0, reduce_only=False, post_only=True,
                        borrow=False):
            self.borrows.append(borrow)
            super().place_order(category, symbol, side, qty, price, link_id,
                                position_idx, reduce_only, post_only)
    venue = Recorder()
    venue.holding = 0.0
    bot = _spot_bot(venue, [], spot_borrow=True, spot_leverage=2)
    bot.cycle()
    assert venue.borrows and all(venue.borrows)  # every order borrows
    plain = Recorder()
    plain.holding = 0.0
    _spot_bot(plain, []).cycle()
    assert plain.borrows and not any(plain.borrows)
