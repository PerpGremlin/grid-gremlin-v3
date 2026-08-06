# Specs for SPEC X1-X6 — every stop path with its on-venue residue stated.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import ConfigError, validate_config
from gridgremlin.events import Notifier

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


def _holding(venue, size='0.021', avg='63000', **extra):
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': size,
                      'avgPrice': avg, 'leverage': '10',
                      'unrealisedPnl': '0', **extra}


# --- X2: the watch matrix ----------------------------------------------------

def spec_X2_mark_price_fires_on_the_losing_side_only():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    assert bot.alive                                   # above the level: lives
    venue.mark = 57900.0
    bot.cycle()
    assert not bot.alive                               # crossed: fires


def spec_X2_account_equity_fires_on_the_shared_pool():
    venue, lines = FakeVenue(), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'account_equity', 'level': 2500})
    bot.cycle(equity=3000.0)
    assert bot.alive
    bot.cycle(equity=2400.0)
    assert not bot.alive


def spec_X2_equity_unknown_is_not_a_breach():
    venue, lines = FakeVenue(), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'account_equity', 'level': 2500})
    bot.cycle(equity=None)
    assert bot.alive                                   # absence never fires


def spec_X2_position_sl_respects_the_hand_placed_stop():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue, stopLoss='58000')                  # the operator's, on-venue
    bot = _bot(venue, lines, stop={'watch': 'position_sl'})
    bot.cycle()
    assert bot.alive
    venue.mark = 57950.0
    bot.cycle()
    assert not bot.alive
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'yours, on the venue' in kill


def spec_X2_position_sl_with_no_venue_stop_never_fires():
    venue, lines = FakeVenue(mark=100.0), []           # mark in the basement
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'position_sl'})
    bot.cycle()
    assert bot.alive                                   # absence is not a breach


# --- X1/X5/X6: fire — flatten grid inventory, floor survives -----------------

def spec_X6_the_floor_core_survives_a_stop():
    venue, lines = FakeVenue(mark=57000.0), []
    _holding(venue, size='0.035')                      # 5 lots: 2 floored + 3 grid
    bot = _bot(venue, lines, min_position_base=0.014,
               stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    assert not bot.alive
    assert venue.position is not None                  # the stack lives
    assert abs(float(venue.position['size']) - 0.014) < 1e-9
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'floor core 0.014 REMAINS' in kill          # X4: residue stated


def spec_X1_no_floor_flattens_everything_and_cancels():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()                                        # ladder rests
    assert venue.orders
    venue.mark = 57000.0
    bot.cycle()
    assert venue.position is None                      # flat (D1: the off button)
    assert venue.orders == []                          # X5: owned orders cancelled
    kill = next(ln for ln in lines if ' kill ' in ln)
    assert 'position flat' in kill and 'nothing owned rests' in kill
    assert bot.cycle() is None                         # dead bots stay dead


# --- X3: server-side — the venue holds it, sized to the scope ----------------

def spec_X3_server_side_rests_on_the_venue_sized_to_inventory():
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue, size='0.035')
    bot = _bot(venue, lines, min_position_base=0.014,
               stop={'watch': 'mark_price', 'level': 58000,
                     'server_side': True})
    bot.cycle()
    level, size = venue.sl_calls[0]
    assert level == 58000.0
    assert abs(size - 0.021) < 1e-9                    # partial: X6's scope
    assert venue.position['stopLoss'] == '58000'       # survives this process
    bot.cycle()
    assert len(venue.sl_calls) == 1                    # the venue already agrees


def spec_X3_server_side_resizes_as_the_position_grows():
    venue, lines = FakeVenue(mark=63000.0), []
    _holding(venue, size='0.021')
    bot = _bot(venue, lines,
               stop={'watch': 'mark_price', 'level': 58000,
                     'server_side': True})
    bot.cycle()
    _holding(venue, size='0.028',                      # a fill deepened it
             stopLoss=venue.position['stopLoss'])
    bot.cycle()
    assert len(venue.sl_calls) == 1                    # full-mode: level unchanged


def spec_X3_refusals():
    for stop in ({'watch': 'account_equity', 'level': 2500, 'server_side': True},
                 {'watch': 'position_sl', 'server_side': True}):
        try:
            _cfg(stop=stop)
        except ConfigError as e:
            assert 'server_side' in str(e)
        else:
            raise AssertionError(f'accepted: {stop}')
    try:
        _cfg(market_type='spot', side='long', leverage=None,
             stop={'watch': 'mark_price', 'level': 1500, 'server_side': True})
    except ConfigError as e:
        assert 'hosts' in str(e)
    else:
        raise AssertionError('spot server-side stop accepted')


# --- the martingale's stop: whole position (no floor concept) ----------------

def spec_X6_martingale_stop_flattens_the_whole_round():
    venue, lines = FakeVenue(mark=59000.0), []
    _holding(venue, size='0.016', avg='60000')
    mcfg = validate_config({'strategy': 'martingale', 'market_type': 'linear',
                            'symbol': 'BTCUSDT', 'side': 'long',
                            'capital': 1000.0, 'leverage': 10,
                            'base_order_size': 500.0, 'safety_order_size': 250.0,
                            'deviation_pct': 0.01, 'max_averaging_orders': 2,
                            'take_profit_avg_pct': 0.01,
                            'stop': {'watch': 'mark_price', 'level': 59500}})
    bot = Bot(mcfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    assert not bot.alive and venue.position is None


# --- I5: the flatten order carries our identity ------------------------------

def spec_I5_the_flatten_order_carries_an_owned_link():
    from gridgremlin.apply import rung_of
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.cycle()
    venue.mark = 57000.0
    bot.cycle()
    assert not bot.alive
    assert rung_of(venue.market_links[-1], bot.botid) == 0


# --- X7: a fired stop survives the process -----------------------------------

def spec_X7_tombstone_lands_BEFORE_the_flatten():
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones
    tmp = _P(tempfile.mkdtemp()) / 'tombs.json'
    order = []

    class Sequenced(FakeVenue):
        def place_market(self, *a, **kw):
            order.append('flatten')
            return super().place_market(*a, **kw)

    class Watching(Tombstones):
        def add(self, botid, reason):
            order.append('tombstone')
            super().add(botid, reason)

    venue, lines = Sequenced(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.tombs = Watching(tmp)
    bot.cycle()
    venue.mark = 57000.0
    bot.cycle()
    assert order[:2] == ['tombstone', 'flatten']   # durable FIRST
    fresh = Tombstones(tmp)                        # a new process
    assert fresh.has(bot.botid)
    assert 'mark_price' in fresh.reason(bot.botid)


def spec_X7_external_close_also_tombstones():
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones
    tmp = _P(tempfile.mkdtemp()) / 'tombs.json'
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines)
    bot.tombs = Tombstones(tmp)
    bot.cycle()
    buy = next(o for o in venue.orders if o['side'] == 'Buy')
    venue.fill(buy['order_id'], buy['price'])
    bot.cycle()                                    # holding now
    venue.position = None                          # owner closes it by hand
    for _ in range(3):                             # E9: confirmed, not guessed
        bot.cycle()
    assert not bot.alive
    assert Tombstones(tmp).has(bot.botid)


# --- audit H2/H3: the conditional book is resized and respected --------------

def spec_X3_partial_SL_resizes_when_the_position_grows():
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue, size='0.035')
    bot = _bot(venue, lines, min_position_base=0.014,
               stop={'watch': 'mark_price', 'level': 58000,
                     'server_side': True})
    bot.cycle()
    assert venue.sl_calls[-1] == (58000.0, 0.021)     # sized to inventory
    venue.position = dict(venue.position, size='0.060')   # grows, SL kept
    bot.cycle()
    assert venue.sl_calls[-1] == (58000.0, 0.046)     # H2: RE-SIZED
    book = venue.stop_orders('linear', 'BTCUSDT')
    sls = [o for o in book if 'StopLoss' in o['stopOrderType']]
    assert len(sls) == 1                              # stale one CANCELLED
    n = len(venue.sl_calls)
    bot.cycle()
    assert len(venue.sl_calls) == n                   # level+size agree: quiet


def spec_I1_foreign_conditionals_are_never_cancelled():
    row = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'BTCUSDT', 'side': 'long', 'capital': 1000.0,
           'leverage': 10, 'base_order_size': 1000.0,
           'safety_order_size': 1000.0, 'order_size_multiplier': 2.0,
           'deviation_pct': 0.01, 'deviation_step_multiplier': 2.0,
           'max_averaging_orders': 3,
           'take_profit_tranches': [{'at_avg_pct': 0.01, 'share': 0.5},
                                    {'at_avg_pct': 0.02, 'share': 0.5}]}
    venue, lines = FakeVenue(), []
    bot = Bot(validate_config(row), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    # an operator's manual TP on the OTHER index — and one on no index
    venue.stop_book = [{'orderId': 'yours1', 'stopOrderType': 'TakeProfit',
                        'triggerPrice': '65000', 'qty': '0.5',
                        'positionIdx': 2},
                       {'orderId': 'yours2', 'stopOrderType': 'TakeProfit',
                        'triggerPrice': '64000', 'qty': '0.5',
                        'positionIdx': 0}]
    bot.cycle()                                       # base
    bot.cycle()                                       # tranches maintained
    ids = {o['orderId'] for o in venue.stop_orders('linear', 'BTCUSDT')}
    assert {'yours1', 'yours2'} <= ids                # H3: untouched


# --- audit M3: the tombstone fails CLOSED, and never blocks the stop ---------

def spec_X7_a_corrupt_tombstone_file_refuses_never_revives():
    import tempfile
    from pathlib import Path as _P
    from gridgremlin.tombstones import Tombstones, TombstoneError
    tmp = _P(tempfile.mkdtemp()) / 'tombs.json'
    tmp.write_text('{not json')
    try:
        Tombstones(tmp)
    except TombstoneError as e:
        assert 'deliberately' in str(e)
    else:
        raise AssertionError('a corrupt tombstone file was swallowed')


def spec_X7_a_failed_tombstone_write_never_blocks_the_flatten():
    class BrokenDisk:
        def add(self, botid, reason):
            raise OSError(30, 'Read-only file system')
    venue, lines = FakeVenue(mark=61000.0), []
    _holding(venue)
    bot = _bot(venue, lines, stop={'watch': 'mark_price', 'level': 58000})
    bot.tombs = BrokenDisk()
    bot.cycle()
    venue.mark = 57000.0
    bot.cycle()
    assert not bot.alive and venue.position is None   # the stop STILL executed
    assert any('tombstone write FAILED' in ln for ln in lines)
