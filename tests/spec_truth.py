# Specs for SPEC V1-V5, E5, E8, I4 — the Bybit truth seam, against fakes.

import os

from gridgremlin.exchange.env import load_env
from gridgremlin.exchange.errors import VenueError
from gridgremlin.exchange.bybit.client import Client, detect_env
from gridgremlin.exchange.bybit.truth import (TruthError, dedup_executions,
                                              parse_instrument, read_orders,
                                              read_positions, read_symbol_truth,
                                              read_wallet, validate_truth)


def _order(i, **over):
    o = {'orderId': f'id{i}', 'orderLinkId': f'bot-{i}-1', 'side': 'Buy',
         'price': '50000', 'qty': '0.001', 'cumExecQty': '0',
         'reduceOnly': False, 'orderStatus': 'New', 'positionIdx': 1,
         'orderType': 'Limit', 'updatedTime': '1700000000000'}
    o.update(over)
    return o


class FakePages:
    """A three-page order book. A one-page reader sees a third of it."""

    def __init__(self):
        self.pages = {None: ([_order(i) for i in range(50)], 'c1'),
                      'c1': ([_order(50 + i) for i in range(50)], 'c2'),
                      'c2': ([_order(100 + i) for i in range(20)], None)}

    def open_orders_page(self, category, symbol, cursor=None):
        rows, nxt = self.pages[cursor]
        return {'list': rows, 'nextPageCursor': nxt}


# --- E5: pagination is followed to the end, or it is an error ----------------

def spec_E5_orders_follow_the_cursor_to_the_end():
    assert len(read_orders(FakePages(), 'linear', 'BTCUSDT')) == 120


def spec_E5_a_runaway_book_raises_partial_read():
    class Endless:
        def open_orders_page(self, category, symbol, cursor=None):
            return {'list': [_order(0)], 'nextPageCursor': 'again'}
    try:
        read_orders(Endless(), 'linear', 'BTCUSDT')
    except VenueError as e:
        assert e.kind == 'partial_read'
    else:
        raise AssertionError('runaway pagination did not raise')


# --- V5: trigger orders never enter order truth ------------------------------

def spec_V5_trigger_orders_are_excluded():
    class OnePage:
        def open_orders_page(self, category, symbol, cursor=None):
            return {'list': [_order(1), _order(2, stopOrderType='StopLoss')],
                    'nextPageCursor': None}
    orders = read_orders(OnePage(), 'linear', 'BTCUSDT')
    assert [o['order_id'] for o in orders] == ['id1']


# --- V1: one schema, refused when broken -------------------------------------

def spec_V1_truth_schema_is_enforced():
    try:
        validate_truth({'symbol': 'X', 'orders': [], 'positions': {}})
    except TruthError as e:
        assert 'missing' in str(e)
    else:
        raise AssertionError('truncated truth validated')


def spec_V1_positions_are_one_shape_with_every_key():
    got = read_positions({'list': [{'positionIdx': '1', 'side': 'Buy',
                                    'size': '0.5', 'avgPrice': '61000',
                                    'stopLoss': '', 'leverage': '10',
                                    'unrealisedPnl': '12.5'}]})
    p = got[1]
    assert p['stop_loss'] is None and p['take_profit'] is None
    assert p['liq_price'] is None and p['avg_entry'] == 61000.0


def spec_V1_wallet_is_one_shape_even_empty():
    w = read_wallet({'list': []})
    assert w['equity'] == 0.0 and w['coins'] == {}
    assert 'mm_rate' in w and 'maint_margin' in w      # the empty-account keys


# --- V2: funding normalised to per-hour at read ------------------------------

class FakeTicker:
    def __init__(self, interval_result):
        self._t = interval_result

    def tickers(self, category, symbol):
        return self._t

    def open_orders_page(self, category, symbol, cursor=None):
        return {'list': [], 'nextPageCursor': None}

    def position_list(self, category, symbol):
        return {'list': []}


def spec_V2_funding_carries_its_unit():
    t8 = {'markPrice': '60000', 'bid1Price': '59999', 'ask1Price': '60001',
          'fundingRate': '0.0008', 'nextFundingTime': '1700000000000'}
    truth = read_symbol_truth(FakeTicker(t8), 'linear', 'BTCUSDT',
                              funding_interval_minutes=480.0)
    assert abs(truth['funding_rate_hourly'] - 0.0001) < 1e-12
    hourly = read_symbol_truth(FakeTicker(t8), 'linear', 'BTCUSDT',
                               funding_interval_minutes=60.0)
    assert abs(hourly['funding_rate_hourly'] - 0.0008) < 1e-12


def spec_V1_split_ref_is_book_mid_with_mark_fallback():
    t = {'markPrice': '60010', 'bid1Price': '59990', 'ask1Price': '60010',
         'fundingRate': '0', 'nextFundingTime': '0'}
    truth = read_symbol_truth(FakeTicker(t), 'linear', 'BTCUSDT')
    assert truth['split_ref'] == 60000.0
    bookless = dict(t, bid1Price='', ask1Price='')
    truth = read_symbol_truth(FakeTicker(bookless), 'linear', 'BTCUSDT')
    assert truth['split_ref'] == 60010.0               # falls back to mark


# --- A1's venue half: the instrument spec ------------------------------------

def spec_A1_instrument_parse_refuses_non_trading():
    info = {'symbol': 'BTCUSDT', 'status': 'Closed',
            'priceFilter': {'tickSize': '0.1'},
            'lotSizeFilter': {'qtyStep': '0.001', 'minOrderQty': '0.001'}}
    try:
        parse_instrument('linear', info)
    except VenueError:
        pass
    else:
        raise AssertionError('non-trading instrument accepted')


def spec_A1_instrument_spec_feeds_the_adapter():
    from gridgremlin.adapters import adapter_for
    info = {'symbol': 'BTCUSDT', 'status': 'Trading', 'settleCoin': 'USDT',
            'fundingInterval': '480',
            'priceFilter': {'tickSize': '0.1'},
            'lotSizeFilter': {'qtyStep': '0.001', 'minOrderQty': '0.001',
                              'minNotionalValue': '5'}}
    a = adapter_for('linear', parse_instrument('linear', info))
    assert a.qty_step == 0.001 and a.min_notional == 5.0


# --- I4: fills dedup by execution id -----------------------------------------

def spec_I4_executions_dedup_by_exec_id():
    seen = set()
    first = dedup_executions(seen, [{'execId': 'a'}, {'execId': 'b'}])
    assert len(first) == 2
    again = dedup_executions(seen, [{'execId': 'b'}, {'execId': 'c'}])
    assert [e['execId'] for e in again] == ['c']


# --- E8 / env resolution -----------------------------------------------------

def spec_E8_transport_failure_raises_not_guesses():
    def broken(url, headers):
        raise OSError('network down')
    c = Client(env='demo', api_key='k', api_secret='s', transport=broken)
    try:
        c.get('/v5/market/time')
    except OSError:
        pass
    else:
        raise AssertionError('a failed read returned something')


def spec_env_demo_flag_resolves_demo_and_comments_strip(tmp='/tmp/v3спec.env'):
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False) as f:
        f.write('FAKE_A=demo # the v2 template accident\nFAKE_B=x\n')
        path = f.name
    os.environ.pop('FAKE_A', None)
    os.environ.pop('FAKE_B', None)
    load_env(path)
    assert os.environ['FAKE_A'] == 'demo'              # comment stripped
    assert os.environ['FAKE_B'] == 'x'
    os.environ.pop('FAKE_A'), os.environ.pop('FAKE_B')
    assert detect_env() in ('demo', 'testnet', 'mainnet')


def spec_rate_limit_glide_sleeps_to_the_window_reset():
    import time as _time
    from gridgremlin.exchange.bybit.client import Client, RATE_LIMIT_FLOOR
    c = Client(env='demo', api_key='k', api_secret='s',
               transport=lambda u, h: {'retCode': 0, 'result': {}})
    slept = []
    real_sleep, _time.sleep = _time.sleep, slept.append
    try:
        now_ms = int(_time.time() * 1000)
        c._glide({'X-Bapi-Limit-Status': '2',
                  'X-Bapi-Limit-Reset-Timestamp': str(now_ms + 1200)})
        c._glide({'X-Bapi-Limit-Status': '40',
                  'X-Bapi-Limit-Reset-Timestamp': str(now_ms + 1200)})
        c._glide({})                              # headerless: no-op
    finally:
        _time.sleep = real_sleep
    assert len(slept) == 1 and 0.5 < slept[0] <= 5.0


# --- V6: spot — the wallet holding IS the position ---------------------------

class SpotClient:
    """No position_list at all: calling it would raise, proving spot truth
    never touches the position endpoint."""

    def tickers(self, category, symbol):
        return {'lastPrice': '44.3', 'bid1Price': '44.2', 'ask1Price': '44.4'}

    def open_orders_page(self, category, symbol, cursor=None):
        return {'list': [], 'nextPageCursor': None}

    def wallet_balance(self):
        return {'list': [{'totalEquity': '1000', 'coin': [
            {'coin': 'LTC', 'walletBalance': '2.5', 'equity': '110',
             'availableToWithdraw': '2.5'}]}]}


def spec_V6_spot_position_is_the_wallet_holding():
    truth = read_symbol_truth(SpotClient(), 'spot', 'LTCUSDT',
                              base_coin='LTC')
    p = truth['positions'][0]
    assert p['side'] == 'Buy' and p['size'] == 2.5
    assert p['avg_entry'] is None                    # the venue keeps no basis
    assert truth['mark'] == 44.3                     # lastPrice fallback
    assert truth['funding_rate_hourly'] is None      # spot has no funding


def spec_V6_no_holding_means_no_position():
    class Flat(SpotClient):
        def wallet_balance(self):
            return {'list': [{'totalEquity': '1000', 'coin': []}]}
    assert read_symbol_truth(Flat(), 'spot', 'LTCUSDT',
                             base_coin='LTC')['positions'] == {}


def spec_V6_spot_truth_without_base_coin_refuses():
    try:
        read_symbol_truth(SpotClient(), 'spot', 'LTCUSDT')
    except TruthError:
        pass
    else:
        raise AssertionError('spot truth guessed a base coin')


def spec_V6_spot_write_bodies_carry_no_position_concepts():
    from gridgremlin.exchange.bybit.client import WriteClient

    class W(WriteClient):
        def __init__(self):
            self.bodies = []

        def post(self, path, body):
            self.bodies.append(body)
            return {}
    w = W()
    w.place_order('spot', 'LTCUSDT', 'Sell', '1', '50', 'x-1-a')
    w.place_market('spot', 'LTCUSDT', 'Buy', '1', link_id='x-0-a')
    w.place_order('linear', 'BTCUSDT', 'Buy', '1', '50', 'x-1-a',
                  position_idx=1)
    spot_limit, spot_market, lin = w.bodies
    assert 'positionIdx' not in spot_limit and 'reduceOnly' not in spot_limit
    assert spot_market['marketUnit'] == 'baseCoin'
    assert 'positionIdx' not in spot_market
    assert lin['positionIdx'] == 1                   # perps unchanged


def spec_V6_dust_below_the_venue_minimum_is_flat():
    """Spot fees settle in the base coin: a full exit leaves a shaving the
    venue itself will not accept as an order (found live 2026-08-05: a
    8.85e-06 LTC residue warned 'nothing harvestable' forever)."""
    class Dusty(SpotClient):
        def wallet_balance(self):
            return {'list': [{'totalEquity': '1000', 'coin': [
                {'coin': 'LTC', 'walletBalance': '0.00000885',
                 'equity': '0.0004', 'availableToWithdraw': '0.00000885'}]}]}
    truth = read_symbol_truth(Dusty(), 'spot', 'LTCUSDT',
                              base_coin='LTC', dust=0.00001)
    assert truth['positions'] == {}
    held = read_symbol_truth(SpotClient(), 'spot', 'LTCUSDT',
                             base_coin='LTC', dust=0.00001)
    assert held['positions'][0]['size'] == 2.5     # real holdings unaffected
