# Specs for SPEC A6's exam and the V contract across BOTH venues. The rule:
# if any strategy file needed touching for the second venue, the seam failed.

from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.exchange.truth import validate_truth, validate_wallet
from gridgremlin.exchange.hyperliquid.adapters import HLPerpAdapter
from gridgremlin.exchange.hyperliquid import truth as hl
from gridgremlin.exchange.bybit import truth as bb

HL_SPEC = hl.parse_instrument({'name': 'SOL', 'szDecimals': 2,
                               'maxLeverage': 50})


# --- A6: the seam exam -------------------------------------------------------

def spec_A6_no_strategy_file_knows_the_second_venue_exists():
    # config.py is exempt: the VENUES enum is the declaration surface — the
    # one place a venue NAME belongs. Strategy and maths must never know.
    for name in ('ladder.py', 'bot.py', 'apply.py', 'window.py',
                 'adapters.py', 'backtest.py', 'events.py'):
        src = Path(f'gridgremlin/{name}').read_text()
        assert 'hyperliquid' not in src.lower(), f'{name} leaked the venue'


def spec_A6_hl_inherits_the_linear_maths_unchanged():
    # not similar code — the SAME functions (M1's rule applied to venues)
    assert HLPerpAdapter.qty_from_notional is LinearAdapter.qty_from_notional
    assert HLPerpAdapter.realised_pnl is LinearAdapter.realised_pnl
    assert HLPerpAdapter.pnl_to_usd is LinearAdapter.pnl_to_usd
    a = HLPerpAdapter(HL_SPEC)
    assert a.one_way_mode and a.position_idx('Buy', False) == 0


def spec_A6_hl_rounding_is_sig_figs_capped_by_decimals():
    a = HLPerpAdapter(HL_SPEC)                     # szDecimals 2 -> 4 places
    assert a.round_price(1867.2534) == 1867.3      # 5 sig figs bind
    assert a.round_price(73.12345) == 73.123       # 5 sig figs again
    assert a.round_price(64000.7) == 64001.0       # quantum never coarser than 1
    tiny = HLPerpAdapter(hl.parse_instrument({'name': 'X', 'szDecimals': 0}))
    assert tiny.round_price(0.1234567) == 0.12346  # 5 sig inside 6 places
    assert a.fmt_price(1867.2534) == '1867.3'      # plain string, no junk


def spec_A6_hl_min_notional_is_the_ten_dollar_floor():
    a = HLPerpAdapter(HL_SPEC)
    assert not a.meets_minimum(0.01, 900.0)        # $9: below the floor
    assert a.meets_minimum(0.02, 900.0)


# --- the V contract, both venues through one validator -----------------------

class FakeHL:
    def meta_and_ctxs(self):
        return ({'universe': [{'name': 'SOL', 'szDecimals': 2}]},
                [{'markPx': '73.5', 'funding': '0.0000125'}])

    def l2_book(self, coin):
        return {'levels': [[{'px': '73.49', 'sz': '10'}],
                           [{'px': '73.51', 'sz': '10'}]]}

    def clearinghouse_state(self):
        return {'marginSummary': {'accountValue': '5000',
                                  'totalMarginUsed': '250'},
                'crossMaintenanceMarginUsed': '25', 'withdrawable': '4000',
                'assetPositions': [{'position': {
                    'coin': 'SOL', 'szi': '1.3', 'entryPx': '73.7',
                    'leverage': {'value': 5}, 'unrealizedPnl': '-0.3'}}]}

    def user_abstraction(self):
        return 'disabled'

    def open_orders(self, coin=None):
        from gridgremlin.exchange.hyperliquid.signing import link_to_cloid
        return [{'coin': 'SOL', 'oid': 77, 'side': 'B', 'limitPx': '73.0',
                 'sz': '1.0', 'origSz': '1.3', 'reduceOnly': False,
                 'isTrigger': False, 'timestamp': 1700000000000,
                 'cloid': link_to_cloid('linSOLl-3-ab12')},
                {'coin': 'SOL', 'oid': 78, 'side': 'A', 'limitPx': '80.0',
                 'sz': '1', 'origSz': '1', 'isTrigger': True}]       # V5: out


def spec_V1_hl_truth_passes_the_shared_schema():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    validate_truth(t)                              # the SAME validator
    assert t['split_ref'] == 73.5
    assert t['market_type'] == 'linear'            # no third category word (M10)


def spec_V2_hl_funding_is_hourly_at_the_source():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    assert t['funding_rate_hourly'] == 0.0000125   # identity, unit in the name


def spec_V5_hl_trigger_orders_are_excluded():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    assert [o['order_id'] for o in t['orders']] == ['77']
    o = t['orders'][0]
    assert o['qty'] == 1.3                         # origSz, not the remainder
    assert abs(o['cum_exec_qty'] - 0.3) < 1e-12    # derived
    assert o['link_id'] == 'linSOLl-3-ab12'        # the cloid DECODES back —
    # without this the diff cannot see its own orders and re-places them every
    # cycle: the live testnet duplicate incident, 2026-08-04, pinned


def spec_V1_hl_positions_are_one_shape_with_every_key():
    t = hl.read_symbol_truth(FakeHL(), 'SOL')
    p = t['positions'][0]
    assert p['stop_loss'] is None and p['take_profit'] is None
    assert p['side'] == 'Buy' and p['size'] == 1.3
    # documented consequence: watch: position_sl is inert on HL — honestly


def spec_V1_hl_wallet_passes_the_shared_schema_with_computed_rates():
    w = hl.read_wallet(FakeHL())
    validate_wallet(w)
    assert w['mm_rate'] == 25.0 / 5000.0           # computed, never venue-sent
    assert w['im_rate'] == 250.0 / 5000.0


def spec_V1_hl_unified_mode_sums_without_double_counting():
    # v2's live measurement: perp margin mirrors as a spot hold — the honest
    # sum is perp accountValue + (spot total - hold)
    class Unified(FakeHL):
        def user_abstraction(self):
            return 'unifiedAccount'

        def clearinghouse_state(self):
            st = dict(FakeHL.clearinghouse_state(self))
            st['marginSummary'] = {'accountValue': '33.47',
                                   'totalMarginUsed': '33.47'}
            return st

        def spot_clearinghouse_state(self):
            return {'balances': [{'coin': 'USDC', 'total': '999.0',
                                  'hold': '33.47'}]}
    w = hl.read_wallet(Unified())
    assert abs(w['equity'] - (33.47 + (999.0 - 33.47))) < 1e-9   # = 999
    assert w['coins']['USDC']['perp'] == 33.47
    assert w['coins']['USDC']['spot'] == 999.0


def spec_V4_the_contract_is_one_module_for_both_venues():
    from gridgremlin.exchange import truth as shared
    assert bb.validate_truth is shared.validate_truth
    assert hl.validate_truth is shared.validate_truth


def spec_F5_hl_mainnet_is_refused_this_phase():
    # the owner manages real positions on HL mainnet; v3 may not even look
    # without an explicit future decision. Testnet-only, structurally.
    from gridgremlin.exchange.errors import VenueError
    from gridgremlin.exchange.hyperliquid.client import InfoClient
    try:
        InfoClient(env='mainnet')
    except VenueError as e:
        assert 'testnet-only' in str(e)
    else:
        raise AssertionError('HL mainnet client was constructible')
    assert InfoClient(env='testnet').base.startswith('https://api.hyperliquid-t')


# --- C7 at the universe seam: a removed coin refuses BY NAME -----------------
# HL removed XRP from its testnet universe mid-soak; the build crashed as a
# bare StopIteration. The refusal must name the coin.

def spec_C7_a_coin_missing_from_the_universe_refuses_by_name():
    from gridgremlin.exchange.errors import VenueError
    from gridgremlin.exchange.hyperliquid.venue import HLVenueClient
    c = HLVenueClient.__new__(HLVenueClient)
    c._universe = {'BTC': (0, {'name': 'BTC'})}
    try:
        c._entry('XRP')
    except VenueError as e:
        assert 'XRP' in str(e)
    else:
        raise AssertionError('a missing coin did not refuse')
