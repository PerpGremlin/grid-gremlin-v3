# Specs for SPEC R1-R5 — the readout: venue fills -> grid profit vs total P&L.

import inspect

from gridgremlin.report import (apply_fill, ledger, new_book, owner_of,
                                total_pnl)
from gridgremlin.exchange.errors import VenueError


def _fill(t, side, price, qty, fee=0.0, link='', symbol='BTCUSDT'):
    return {'time_ms': t, 'side': side, 'price': price, 'qty': qty,
            'fee': fee, 'link_id': link, 'symbol': symbol,
            'exec_id': f'e{t}'}


# --- R1: ownership is the link prefix, exactly I1's rule ---------------------

def spec_R1_a_fill_is_ours_iff_the_link_parses():
    bots = ['linBTCUSDTl', 'linETHUSDTs']
    assert owner_of('linBTCUSDTl-3-ab12', bots) == 'linBTCUSDTl'
    assert owner_of('linBTCUSDTlx-3-a', bots) is None      # not our prefix
    assert owner_of('linBTCUSDTl-x-a', bots) is None       # rung must parse
    assert owner_of('', bots) is None


# --- R2: average-cost arithmetic ---------------------------------------------

def spec_R2_long_build_then_partial_exit():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.1)
    apply_fill(b, 'buy', 110.0, 1.0, 0.1)
    assert abs(b['avg_cost'] - 105.0) < 1e-9
    apply_fill(b, 'sell', 120.0, 1.5, 0.2)
    assert abs(b['realized'] - 22.5) < 1e-9
    assert abs(b['position'] - 0.5) < 1e-9
    assert abs(b['avg_cost'] - 105.0) < 1e-9               # reduce keeps basis
    assert abs(b['fees'] - 0.4) < 1e-9


def spec_R2_short_side_realises_on_the_buy():
    b = new_book()
    apply_fill(b, 'sell', 100.0, 2.0, 0.0)
    apply_fill(b, 'buy', 90.0, 1.0, 0.0)
    assert abs(b['realized'] - 10.0) < 1e-9
    assert abs(b['position'] - -1.0) < 1e-9


def spec_R2_flip_through_zero_reanchors():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'sell', 90.0, 2.0, 0.0)
    assert abs(b['realized'] - -10.0) < 1e-9
    assert abs(b['position'] - -1.0) < 1e-9
    assert abs(b['avg_cost'] - 90.0) < 1e-9                # remainder opens here


def spec_R2_full_close_zeroes_the_book():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'sell', 105.0, 1.0, 0.0)
    assert b['position'] == 0.0 and b['avg_cost'] == 0.0
    assert abs(b['realized'] - 5.0) < 1e-9


# --- R3: unowned fills are reported, never dropped ---------------------------

def spec_R3_external_activity_gets_its_own_bucket():
    fills = [_fill(1, 'buy', 100.0, 1.0, link='linBTCUSDTl-0-ab'),
             _fill(2, 'sell', 101.0, 0.5, link='')]
    books = ledger(fills, ['linBTCUSDTl'])
    assert 'linBTCUSDTl' in books
    assert ('unowned', 'BTCUSDT') in books
    assert books[('unowned', 'BTCUSDT')]['fills'] == 1


def spec_R3_ledger_orders_by_time_not_arrival():
    fills = [_fill(2, 'sell', 120.0, 1.0, link='linBTCUSDTl-1-ab'),
             _fill(1, 'buy', 100.0, 1.0, link='linBTCUSDTl-0-ab')]
    b = ledger(fills, ['linBTCUSDTl'])['linBTCUSDTl']
    assert abs(b['realized'] - 20.0) < 1e-9                # buy first, then sell


# --- R4: read-only by construction -------------------------------------------

def spec_R4_no_write_client_in_the_readout():
    import gridgremlin.report as report
    src = inspect.getsource(report)
    for forbidden in ('WriteClient', 'place_order', 'place_market',
                      'exchange_action', 'cancel_order'):
        assert forbidden not in src, f'readout touches {forbidden}'


# --- R5: total P&L ------------------------------------------------------------

def spec_R5_total_adds_mark_to_average_on_the_open_remainder():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 1.0)
    apply_fill(b, 'buy', 110.0, 1.0, 1.0)
    apply_fill(b, 'sell', 120.0, 1.5, 1.0)
    assert abs(total_pnl(b, 120.0) - (22.5 - 3.0 + 7.5)) < 1e-9
    assert total_pnl(b, None) is None                      # open + no mark
    flat = new_book()
    apply_fill(flat, 'buy', 100.0, 1.0, 0.5)
    apply_fill(flat, 'sell', 105.0, 1.0, 0.5)
    assert abs(total_pnl(flat, None) - 4.0) < 1e-9         # flat needs no mark


# --- R1 at the Bybit seam: windows, cursors, Trade-only, dedup ---------------

class FakeExec:
    def __init__(self):
        self.calls = []
        self.rows = [
            {'execId': 'a', 'execType': 'Trade', 'execTime': '2',
             'symbol': 'BTCUSDT', 'side': 'Buy', 'execPrice': '100',
             'execQty': '1', 'execFee': '0.1', 'orderLinkId': 'x-0-a'},
            {'execId': 'f', 'execType': 'Funding', 'execTime': '3',
             'symbol': 'BTCUSDT', 'side': 'Buy', 'execPrice': '0',
             'execQty': '0', 'execFee': '0.5', 'orderLinkId': ''},
            {'execId': 'a', 'execType': 'Trade', 'execTime': '2',
             'symbol': 'BTCUSDT', 'side': 'Buy', 'execPrice': '100',
             'execQty': '1', 'execFee': '0.1', 'orderLinkId': 'x-0-a'}]

    def executions_page(self, category, symbol, start_ms, end_ms, cursor=None):
        self.calls.append((start_ms, end_ms, cursor))
        return {'list': self.rows, 'nextPageCursor': None}


def spec_R1_bybit_fills_window_filter_and_dedup():
    from gridgremlin.exchange.bybit.truth import SEVEN_DAYS_MS, read_fills
    fake = FakeExec()
    fills = read_fills(fake, 'linear', 'BTCUSDT', 0, SEVEN_DAYS_MS + 10)
    assert len(fake.calls) == 2                            # 8 days -> 2 windows
    assert [f['exec_id'] for f in fills] == ['a']          # Trade-only, deduped
    assert fills[0]['side'] == 'buy' and fills[0]['fee'] == 0.1


def spec_R1_bybit_runaway_history_raises_partial_read():
    from gridgremlin.exchange.bybit.truth import read_fills

    class Endless(FakeExec):
        def executions_page(self, *a, cursor=None):
            return {'list': [], 'nextPageCursor': 'again'}
    try:
        read_fills(Endless(), 'linear', 'BTCUSDT', 0, 1000)
    except VenueError as e:
        assert e.kind == 'partial_read'
    else:
        raise AssertionError('runaway pagination did not raise')


# --- R1 at the HL seam: cloid decodes back to the link -----------------------

def spec_R1_hl_fills_decode_the_cloid():
    from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
    from gridgremlin.exchange.hyperliquid.truth import read_fills
    raw = [{'coin': 'XRP', 'px': '3.0', 'sz': '10', 'side': 'B',
            'time': 2, 'tid': 42, 'fee': '0.01',
            'cloid': link_to_cloid('linXRPl-0-ab')},
           {'coin': 'ETH', 'px': '2500', 'sz': '1', 'side': 'A',
            'time': 1, 'tid': 41, 'fee': '0.5', 'cloid': None},
           {'coin': 'BTC', 'px': '60000', 'sz': '1', 'side': 'B',
            'time': 3, 'tid': 40, 'fee': '1'}]
    fills = read_fills(raw, {'XRP', 'ETH'})
    assert [f['symbol'] for f in fills] == ['ETH', 'XRP']  # time-ordered, filtered
    xrp = fills[1]
    assert xrp['link_id'] == 'linXRPl-0-ab' and xrp['side'] == 'buy'
    assert xrp['exec_id'] == '42'
    assert fills[0]['side'] == 'sell' and fills[0]['link_id'] == ''


# --- A4 reaches the readout: inverse books realise in the BASE coin ----------

def spec_R2_an_inverse_book_realises_in_base_coin():
    b = new_book()
    apply_fill(b, 'buy', 50000.0, 1000, 0.0, inverse=True)   # $1000 contracts
    apply_fill(b, 'sell', 62500.0, 1000, 0.0, inverse=True)
    assert abs(b['realized'] - 1000 * (1 / 50000 - 1 / 62500)) < 1e-12   # BTC
    assert abs(b['realized'] - 0.004) < 1e-9


def spec_R5_inverse_total_converts_to_quote_at_mark():
    b = new_book()
    apply_fill(b, 'buy', 50000.0, 1000, 0.0, inverse=True)
    from gridgremlin.report import unreal_pnl
    u = unreal_pnl(b, 62500.0)
    assert abs(u - 0.004) < 1e-9                       # base coin
    assert abs(total_pnl(b, 62500.0) - 250.0) < 1e-6   # $ at mark
    assert total_pnl(b, None) is None                  # open + no mark


# --- audit M2: spot fees settle in the base coin -----------------------------

def spec_R2_spot_base_coin_fees_are_quote_normalised():
    from gridgremlin.exchange.bybit.truth import read_fills

    class SpotExec:
        def executions_page(self, category, symbol, s, e, cursor=None):
            return {'list': [
                {'execId': 'b', 'execType': 'Trade', 'execTime': '2',
                 'symbol': 'LTCUSDT', 'side': 'Buy', 'execPrice': '50',
                 'execQty': '1', 'execFee': '0.001', 'feeCurrency': 'LTC',
                 'orderLinkId': 'x-1-a'},
                {'execId': 's', 'execType': 'Trade', 'execTime': '3',
                 'symbol': 'LTCUSDT', 'side': 'Sell', 'execPrice': '52',
                 'execQty': '1', 'execFee': '0.052', 'feeCurrency': 'USDT',
                 'orderLinkId': 'x-2-a'}], 'nextPageCursor': None}
    fills = read_fills(SpotExec(), 'spot', 'LTCUSDT', 0, 1000)
    assert abs(fills[0]['fee'] - 0.05) < 1e-12      # 0.001 LTC @ 50 -> quote
    assert abs(fills[1]['fee'] - 0.052) < 1e-12     # already quote: untouched


# --- R6: the activity layer — same fills, no new state -----------------------

def spec_R6_every_realisation_is_a_trip():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0)
    apply_fill(b, 'sell', 102.0, 1.0, 0.0)       # trip 1 (+2, flat)
    apply_fill(b, 'buy', 101.0, 1.0, 0.0)
    apply_fill(b, 'sell', 100.0, 0.5, 0.0)       # trip 2 — underwater churn
    assert b['trips'] == 2                       # counted even at a loss
    assert abs(b['realized'] - (2.0 - 0.5)) < 1e-9


def spec_R6_rounds_close_on_flat_and_carry_their_pnl():
    b = new_book()
    link = 'x'
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'buy', 99.0, 1.0, 0.0, entry_side='buy', rung=1)   # SO 1
    apply_fill(b, 'buy', 98.0, 2.0, 0.0, entry_side='buy', rung=2)   # SO 2
    apply_fill(b, 'sell', 100.0, 4.0, 0.0, entry_side='buy')         # TP: flat
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'sell', 101.0, 1.0, 0.0, entry_side='buy')         # round 2
    assert b['rounds'] == 2
    assert b['so_fills'] == 2 and b['max_depth'] == 2
    # round 1: avg (100+99+196)/4 = 98.75 -> +5; round 2: +1
    assert abs(b['round_pnl_sum'] - 6.0) < 1e-9


def spec_R6_depth_resets_between_rounds():
    b = new_book()
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'buy', 99.0, 1.0, 0.0, entry_side='buy', rung=3)
    apply_fill(b, 'sell', 101.0, 2.0, 0.0, entry_side='buy')
    apply_fill(b, 'buy', 100.0, 1.0, 0.0, entry_side='buy', rung=0)
    apply_fill(b, 'buy', 99.5, 1.0, 0.0, entry_side='buy', rung=1)
    apply_fill(b, 'sell', 101.0, 2.0, 0.0, entry_side='buy')
    assert b['max_depth'] == 3                   # the high-water survives
    assert b['_round_depth'] == 0                # but the round gauge reset


def spec_R6_the_ledger_threads_rungs_from_links():
    fills = [_fill(1, 'buy', 100.0, 1.0, link='linBTCUSDTl-0-aa'),
             _fill(2, 'buy', 99.0, 1.0, link='linBTCUSDTl-2-ab'),
             _fill(3, 'sell', 101.0, 2.0, link='linBTCUSDTl-0-ac')]
    b = ledger(fills, ['linBTCUSDTl'],
               entry_sides={'linBTCUSDTl': 'buy'})['linBTCUSDTl']
    assert b['so_fills'] == 1 and b['max_depth'] == 2 and b['rounds'] == 1
