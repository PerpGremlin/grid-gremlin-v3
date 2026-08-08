"""Spot-specific invariants, pinned through cycle() — never through the bare
function. G15 existed as a correct, tested, UNWIRED function while the live
fleet churned 36 zero-spread round trips (2026-08-06); a spec that calls the
function directly cannot see that. These call the whole bot."""
import sys
import time

sys.path.insert(0, 'tests')
from spec_loop import FakeVenue

from gridgremlin.adapters import SpotAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import validate_grid
from gridgremlin.events import Notifier

ADA_SPEC = {'symbol': 'ADAUSDT', 'qty_step': 0.01, 'min_qty': 1.0,
            'price_tick': 0.0001, 'min_notional': 1.0}


class FakeSpotVenue(FakeVenue):
    """Spot: the wallet holding IS the position; fills are queryable."""

    def __init__(self, mark=0.1950, base=953.73):
        super().__init__(mark=mark)
        self.base = base
        self.fill_log = []

    def read_symbol_truth(self, market_type, symbol, funding_interval=480.0):
        from gridgremlin.exchange.bybit.truth import read_symbol_truth
        return read_symbol_truth(self, market_type, symbol, funding_interval,
                                 base_coin='ADA', dust=1.0)

    def tickers(self, category, symbol):
        return {'markPrice': str(self.mark),
                'bid1Price': str(self.mark - 0.0001),
                'ask1Price': str(self.mark + 0.0001),
                'fundingRate': '0', 'nextFundingTime': '0'}

    def wallet_balance(self):
        return {'list': [{'accountType': 'UNIFIED', 'totalEquity': '10000',
                          'coin': [{'coin': 'ADA',
                                    'walletBalance': str(self.base),
                                    'usdValue': '200'}]}]}

    def fills_history(self, market_type, symbol, since_ms, until_ms):
        return [f for f in self.fill_log if since_ms <= f['time_ms'] <= until_ms]

    def record_fill(self, side, price, qty, link_id):
        # strictly increasing, strictly PAST timestamps — a same-millisecond
        # tie makes "newest first" undefined, and a future stamp falls out
        # of the history window entirely
        self.fill_log.append({'side': side, 'price': price, 'qty': qty,
                              'fee': 0.0,
                              'time_ms': (int(time.time() * 1000) - 60_000
                                          + len(self.fill_log) * 1000),
                              'link_id': link_id, 'venue_closed': False,
                              'venue_kind': '', 'market_type': 'spot'})

    def fill_order(self, order):
        """A resting order fills: leaves the book, moves the wallet."""
        self.orders = [o for o in self.orders if o is not order]
        qty = float(order['qty'])
        self.base += -qty if order['side'] == 'Sell' else qty
        self.record_fill(order['side'].lower(), order['price'], qty,
                         order['link_id'])


def _spot_cfg(**over):
    cfg = {'market_type': 'spot', 'symbol': 'ADAUSDT', 'side': 'long',
           'capital': 1500, 'lower': 0.155, 'upper': 0.23, 'rungs': 16,
           'spot_borrow': True, 'spot_leverage': 2,
           'stop': {'watch': 'mark_price', 'level': 0.148}}
    cfg.update(over)
    return validate_grid(cfg)


def _spot_bot(venue, lines, **over):
    return Bot(_spot_cfg(**over), SpotAdapter(ADA_SPEC), venue,
               Notifier(sink=lines.append), gen_seed=1)


def spec_G15_the_derived_basis_reaches_the_exit_floor_through_cycle():
    """The venue reports no spot basis, the config states none — the fill
    history still knows the cost, and the exit must CLEAR it. Live failure:
    the derivation existed, tested, unwired; exits sat at the bought rung
    and the grid paid fees both ways at zero spread."""
    venue, lines = FakeSpotVenue(mark=0.1950, base=953.73), []
    venue.record_fill('buy', 0.1964, 954.68, 'spoADAUSDTl-9-1')
    bot = _spot_bot(venue, lines)
    for mark in (0.1950, 0.1970, 0.1950, 0.1970):   # the live wobble
        venue.mark = mark
        bot.cycle()
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    assert sells, 'holding with no exit resting'
    assert all(o['price'] >= 0.1964 * 1.0025 for o in sells), \
        f'exit below the fee floor of its own cost: {sells}'
    assert any('reconstructed from the newest venue fills' in ln
               for ln in lines), \
        'the derivation must be WIRED, not merely correct'
    # and the exit rung no longer flip-flops with the ref wobble
    assert not any('cancel' in ln and 'Sell' in ln for ln in lines)


def spec_D1_our_own_exit_fill_is_a_trip_not_an_external_close():
    """A link vanishes the same way whether it filled or we cancelled it in
    the last replace — so absence proves nothing. When the link-set
    discriminator fails (it did, live), the venue's fill history decides.
    Live failure: a healthy bot tombstoned itself on its own take-profit."""
    venue, lines = FakeSpotVenue(), []
    venue.record_fill('buy', 0.1964, 954.68, 'spoADAUSDTl-9-0')
    bot = _spot_bot(venue, lines)
    bot.cycle()
    sell = next(o for o in venue.orders if o['side'] == 'Sell')
    venue.fill_order(sell)
    venue.base = 0.00322                       # the live dust, exactly
    bot._exit_links_last = set()               # the race, deterministically
    for _ in range(4):
        bot.cycle()
    assert bot.alive, 'stood down on its own take-profit'
    assert not any('kill' in ln for ln in lines)
    assert any(o['side'] == 'Buy' for o in venue.orders), 'no replenish'


def spec_D1_an_unlinked_close_still_stands_down():
    """The same flat transition, but the venue's last fill carries no link
    of ours: an outside hand sold the holding. That IS an external close —
    the fills check must not make the bot blind to the real thing."""
    import tempfile
    from pathlib import Path
    from gridgremlin.tombstones import Tombstones
    venue, lines = FakeSpotVenue(), []
    venue.record_fill('buy', 0.1964, 954.68, 'spoADAUSDTl-9-0')
    bot = _spot_bot(venue, lines)
    bot.tombs = Tombstones(Path(tempfile.mkdtemp()) / 'tombs.json')
    bot.cycle()
    sell = next(o for o in venue.orders if o['side'] == 'Sell')
    venue.record_fill('sell', sell['price'], float(sell['qty']), '')
    venue.base = 0.00322                       # sold, but not by us
    bot._exit_links_last = set()
    for _ in range(4):
        bot.cycle()
    assert not bot.alive
    assert any('closed by' in ln for ln in lines)


def spec_G15_a_lagging_fill_list_withholds_exits_not_prices_them_blind():
    """The wallet moves before the fill list does. Live: an exit placed 6s
    after a buy the fill list had not yet published rested at the freshly
    bought rung — zero spread, fees both ways. When fills cannot COVER the
    holding, there is no basis and there are no exits, until the account
    arrives."""
    venue, lines = FakeSpotVenue(mark=0.2050, base=904.88), []
    # history knows only an OLD completed trip — not the buy that created
    # the current holding
    venue.record_fill('buy', 0.1913, 980.13, 'spoADAUSDTl-8-1')
    venue.record_fill('sell', 0.1913, 979.15, 'spoADAUSDTl-8-2')
    bot = _spot_bot(venue, lines)
    bot.cycle()
    assert not any(o['side'] == 'Sell' for o in venue.orders), \
        'exit placed with no coverable cost'
    assert not any('nothing harvestable' in ln for ln in lines), \
        'the transient lag must not page the operator'
    # the account arrives: the buy that created the holding becomes visible
    venue.record_fill('buy', 0.207, 905.79, 'spoADAUSDTl-11-3')
    bot.cycle()
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    assert sells, 'account arrived but no exit followed'
    assert all(o['price'] >= 0.207 * 1.0025 for o in sells), \
        f'exit below the TRUE cost of the holding: {sells}'
    # and the basis is the newest covering fill, not an all-history average
    assert any('basis 0.207 ' in ln for ln in lines), lines


def spec_G15_defer_freezes_the_exit_side_but_never_tears_it_down():
    """Audit 2026-08-07 H5: the defer filter fed the cancel diff, so every
    fills-lag window cancelled correctly-priced RESTING exits and re-placed
    them seconds later. Deferral means: create nothing, cancel nothing."""
    venue, lines = FakeSpotVenue(mark=0.1950, base=953.73), []
    venue.record_fill('buy', 0.1964, 954.68, 'spoADAUSDTl-9-1')
    bot = _spot_bot(venue, lines)
    bot.cycle()
    resting = [o for o in venue.orders if o['side'] == 'Sell']
    assert resting
    # wallet moves (a new buy), fills lag: basis unreconstructable
    venue.base = 1900.0
    bot._basis_cache = None
    bot.cycle()
    still = [o for o in venue.orders if o['side'] == 'Sell']
    assert still == resting, 'deferral tore down the resting exit ladder'
    assert not any('cancel' in ln and 'Sell' in ln for ln in lines)


def spec_S5_a_sub_minimum_sliver_logs_and_never_pages():
    """A partial fill leaves a holding below the venue minimum for seconds
    — routine, self-resolving, and it paged the operator twice in an hour
    (live 2026-08-07). The page is reserved for the state that needs an
    operator: basis beyond the range."""
    # 2 ADA clears the dust rule but its notional (~$0.39) is under the
    # venue's $1 minimum — sellable, yet no exit can legally rest
    venue, lines = FakeSpotVenue(mark=0.1950, base=2.0), []
    venue.record_fill('buy', 0.1950, 2.0, 'spoADAUSDTl-9-1')
    bot = _spot_bot(venue, lines)
    bot.cycle()
    assert not any('] warn' in ln and 'harvestable' in ln for ln in lines)
    assert any('below the venue minimum' in ln for ln in lines), lines


def spec_D1_an_outside_close_behind_our_own_cancel_still_stands_down():
    """A link vanishes identically whether it filled or we cancelled it —
    and an outside flatten coinciding with a routine replace slipped
    through as a benign trip (audit 2026-08-07 MED). The fills question
    is asked on the fast path too."""
    import tempfile
    from pathlib import Path
    from gridgremlin.tombstones import Tombstones
    venue, lines = FakeSpotVenue(), []
    venue.record_fill('buy', 0.1964, 954.68, 'spoADAUSDTl-9-0')
    bot = _spot_bot(venue, lines)
    bot.tombs = Tombstones(Path(tempfile.mkdtemp()) / 'tombs.json')
    bot.cycle()
    sell = next(o for o in venue.orders if o['side'] == 'Sell')
    venue.orders = [o for o in venue.orders if o is not sell]   # we "cancel"
    venue.record_fill('sell', 0.1970, 953.73, '')   # an outside hand sold
    venue.base = 0.00322
    bot._exit_links_last = {sell['link_id']}        # link vanished = fast path
    bot.cycle()
    assert not bot.alive, 'an outside close passed as a trip'
    assert any('closed by an outside close' in ln for ln in lines)


def spec_G15_the_coverage_walk_nets_interleaved_sells_correctly():
    """Prior-art adoption item 2 (passivbot's arithmetic): sells inside
    the window must consume OLDER buys during the walk, so the covering
    set is the newest surviving lots — not a buys-only selection. Hand
    case: buy 100@10 (old), sell 50 (sold from that old lot), buy 60@20
    (new); holding 110 = the 60 new + 50 surviving old.
    basis = (60x20 + 50x10) / 110 = 15.4545..."""
    venue, lines = FakeSpotVenue(mark=20.0, base=110.0), []
    venue.record_fill('buy', 10.0, 100.0, 'spoADAUSDTl-3-1')
    venue.record_fill('sell', 12.0, 50.0, 'spoADAUSDTl-4-2')
    venue.record_fill('buy', 20.0, 60.0, 'spoADAUSDTl-5-3')
    bot = _spot_bot(venue, lines)
    basis = bot._derive_basis(110.0)
    assert basis is not None
    assert abs(basis - (60 * 20 + 50 * 10) / 110.0) < 1e-9, basis
    # and a sell larger than every remaining buy still refuses (coverage)
    venue2, _ = FakeSpotVenue(mark=20.0, base=110.0), []
    venue2.record_fill('buy', 10.0, 40.0, 'spoADAUSDTl-3-1')
    venue2.record_fill('sell', 12.0, 50.0, 'spoADAUSDTl-4-2')
    bot2 = _spot_bot(venue2, [].append and [] or [])
    assert bot2._derive_basis(110.0) is None
