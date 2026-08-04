# Specs for SPEC W1-W3, T2 (two cycles), and the event routing — fake venue.

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import validate_config
from gridgremlin.events import Notifier
from gridgremlin.window import window

ADAPTER = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'min_notional': 5.0, 'settle_coin': 'USDT'})


def _cfg(**over):
    row = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long',
           'capital': 1000.0, 'leverage': 10, 'upper': 70000.0,
           'lower': 50000.0, 'rungs': 21, 'spacing_type': 'fixed'}
    row.update(over)
    return validate_config(row)


class FakeVenue:
    """The client surface the Bot uses, backed by an in-memory book."""

    def __init__(self, mark=60000.0):
        self.mark = mark
        self.orders = []
        self.position = None          # dict or None
        self._oid = 0

    # reads (the truth functions call these)
    def tickers(self, category, symbol):
        return {'markPrice': str(self.mark), 'bid1Price': str(self.mark - 0.5),
                'ask1Price': str(self.mark + 0.5), 'fundingRate': '0',
                'nextFundingTime': '0'}

    def open_orders_page(self, category, symbol, cursor=None):
        rows = [{'orderId': o['order_id'], 'orderLinkId': o['link_id'],
                 'side': o['side'], 'price': str(o['price']),
                 'qty': o['qty'], 'cumExecQty': '0',
                 'reduceOnly': o['reduce_only'], 'orderStatus': 'New',
                 'positionIdx': o['position_idx'], 'orderType': 'Limit',
                 'updatedTime': '0'} for o in self.orders]
        return {'list': rows, 'nextPageCursor': None}

    def position_list(self, category, symbol):
        return {'list': [self.position] if self.position else []}

    # writes
    def place_order(self, category, symbol, side, qty, price, link_id,
                    position_idx=0, reduce_only=False, post_only=True):
        self._oid += 1
        self.orders.append({'order_id': f'o{self._oid}', 'link_id': link_id,
                            'side': side, 'price': float(price), 'qty': qty,
                            'reduce_only': reduce_only,
                            'position_idx': position_idx})

    def cancel_order(self, category, symbol, order_id):
        self.orders = [o for o in self.orders if o['order_id'] != order_id]

    def amend_order(self, category, symbol, order_id, qty):
        for o in self.orders:
            if o['order_id'] == order_id:
                o['qty'] = qty

    def place_market(self, category, symbol, side, qty, position_idx=0):
        self.position = {'positionIdx': position_idx, 'side': side,
                         'size': qty, 'avgPrice': str(self.mark),
                         'leverage': '10', 'unrealisedPnl': '0'}

    def set_trading_stop(self, category, symbol, take_profit, position_idx):
        self.tp_calls = getattr(self, 'tp_calls', [])
        self.tp_calls.append(float(take_profit))
        if self.position:
            self.position['takeProfit'] = take_profit

    def fill(self, order_id, avg):
        """Simulate a taker sweep: order gone, position appears."""
        o = next(x for x in self.orders if x['order_id'] == order_id)
        self.orders = [x for x in self.orders if x['order_id'] != order_id]
        self.position = {'positionIdx': o['position_idx'], 'side': o['side'],
                         'size': o['qty'], 'avgPrice': str(avg),
                         'leverage': '10', 'unrealisedPnl': '0'}


def _bot(venue, sink, **cfg_over):
    return Bot(_cfg(**cfg_over), ADAPTER, venue,
               Notifier(sink=sink), gen_seed=1)


# --- W1-W3 -------------------------------------------------------------------

def spec_W1_window_filters_placement_only():
    desired = [{'price': p, 'side': 'Buy', 'qty': 0.001, 'rung': i,
                'reduce_only': False}
               for i, p in enumerate([50000.0, 59000.0, 61000.0, 70000.0])]
    live = window(desired, 60000.0, 0.05)
    assert [o['price'] for o in live] == [59000.0, 61000.0]


def spec_W3_a_resting_in_plan_order_outside_the_window_is_left_alone():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines.append, place_within_pct=0.02)
    bot.cycle()
    n = len(venue.orders)
    venue.mark = 61500.0            # drift: some resting entries fall outside
    bot.cycle()
    kept = {o['order_id'] for o in venue.orders}
    assert n and all(f'o{i+1}' in kept for i in range(n))   # none cancelled


# --- T2: two cycles ----------------------------------------------------------

def spec_T2_second_cycle_is_a_no_op_diff():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines.append)
    first = bot.cycle()
    assert first['creates'] > 0
    second = bot.cycle()
    assert (second['amends'], second['cancels'], second['creates']) == (0, 0, 0)


def spec_T2_a_fill_reprices_the_plan_and_emits_the_event():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines.append)
    bot.cycle()
    buy = next(o for o in venue.orders if o['side'] == 'Buy')
    venue.fill(buy['order_id'], buy['price'])
    result = bot.cycle()
    assert any('[ship] fill' in ln for ln in lines)
    sells = [o for o in venue.orders if o['side'] == 'Sell']
    assert sells and all(o['reduce_only'] for o in sells)   # covered, one lot
    assert result['creates'] >= 1


def spec_T2_no_phantom_fill_on_the_first_cycle():
    venue, lines = FakeVenue(), []
    venue.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.007',
                      'avgPrice': '59000', 'leverage': '10',
                      'unrealisedPnl': '0'}
    bot = _bot(venue, lines.append)
    bot.cycle()                     # adopting, not filling
    assert not any('fill' in ln for ln in lines if '[ship]' in ln)


# --- events: order mechanics logged, not shipped -----------------------------

def spec_order_events_log_and_everything_else_ships():
    venue, lines = FakeVenue(), []
    bot = _bot(venue, lines.append)
    bot.cycle()
    placed = [ln for ln in lines if ' placed ' in ln]
    assert placed and all(ln.startswith('[log]') for ln in placed)
    n = Notifier(ship_orders=True, sink=lines.append)
    n.event('placed', 'x', 'y')
    assert lines[-1].startswith('[ship]')
    n.event('warn', 'x', 'y')
    assert lines[-1].startswith('[ship]')
