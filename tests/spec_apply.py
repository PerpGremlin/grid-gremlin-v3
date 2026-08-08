# Specs for SPEC I1-I3 and E2's decision half, plus the E6/E7 matrix.

from gridgremlin.adapters import LinearAdapter, SpotAdapter
from gridgremlin.apply import (bot_identity, check_fleet_unique,
                               check_link_fits, diff, make_botid, make_link,
                               matches, pair_amends, rung_of)
from gridgremlin.config import ConfigError
from gridgremlin.exchange.errors import KINDS, KIND_REACTIONS

BOT = 'linBTCUSDTl'


def _desired(rung, price, qty, side='Buy', ro=False):
    return {'rung': rung, 'side': side, 'price': price, 'qty': qty,
            'reduce_only': ro}


def _resting(rung, price, qty, side='Buy', ro=False, link=None, gen='a1'):
    return {'order_id': f'oid{rung}', 'link_id': link or make_link(BOT, rung, gen),
            'side': side, 'price': price, 'qty': qty, 'cum_exec_qty': 0.0,
            'reduce_only': ro, 'status': 'New', 'position_idx': 1,
            'order_type': 'Limit', 'updated_time_ms': 0}


# --- I1: identity and ownership ----------------------------------------------

def spec_I1_botid_strips_hyphens():
    assert make_botid('linear', 'BTC-PERP', 'long') == 'linBTCPERPl'
    assert make_botid('spot', 'ETHUSDT', 'short') == 'spoETHUSDTs'


def spec_I1_rung_of_is_the_ownership_guard():
    assert rung_of(make_link(BOT, 7, 1722), BOT) == 7
    assert rung_of('my-own-stop-loss', BOT) is None          # the manual order
    assert rung_of(f'{BOT}-junk-1', BOT) is None             # unparseable tail
    assert rung_of('otherbot-7-100', BOT) is None            # foreign prefix
    assert rung_of(None, BOT) is None


def spec_I2_one_bot_per_identity():
    hedge = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                           'price_tick': 0.1, 'min_qty': 0.001})
    long_cfg = {'market_type': 'linear', 'symbol': 'BTCUSDT', 'side': 'long'}
    short_cfg = dict(long_cfg, side='short')
    a = bot_identity(long_cfg, hedge)
    b = bot_identity(short_cfg, hedge)
    assert a != b                          # hedge legs coexist (idx 1 vs 2)
    check_fleet_unique([('botA', a), ('botB', b)])
    try:
        check_fleet_unique([('botA', a), ('botC', a)])
    except ConfigError as e:
        assert 'one bot per' in str(e)
    else:
        raise AssertionError('identity collision accepted')


def spec_I2_spot_and_linear_are_distinct_identities():
    spot = SpotAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                        'price_tick': 0.1, 'min_qty': 0.001})
    lin = LinearAdapter({'symbol': 'BTCUSDT', 'qty_step': 0.001,
                         'price_tick': 0.1, 'min_qty': 0.001,
                         'one_way_mode': True})
    s = bot_identity({'market_type': 'spot', 'symbol': 'BTCUSDT',
                      'side': 'long'}, spot)
    l = bot_identity({'market_type': 'linear', 'symbol': 'BTCUSDT',
                      'side': 'long'}, lin)
    assert s != l


def spec_I3_link_length_refuses_at_build():
    check_link_fits(BOT, 999, venue_limit=36)
    try:
        check_link_fits('linSOMEVERYLONGSYMBOLNAMEUSDTl', 999, venue_limit=36)
    except ConfigError as e:
        assert 'venue limit' in str(e)
    else:
        raise AssertionError('oversized link accepted')


# --- E2 decisions: keep / cancel / create ------------------------------------

def spec_E2_matching_orders_are_kept():
    desired = [_desired(3, 53000.0, 0.008)]
    resting = [_resting(3, 53000.0, 0.008)]
    cancel, create = diff(desired, resting, BOT)
    assert cancel == [] and create == []                     # steady state


def spec_E2_foreign_orders_are_invisible():
    resting = [_resting(3, 53000.0, 0.008, link='my-own-stop-loss'),
               _resting(4, 54000.0, 0.008, link='otherbot-4-9')]
    cancel, create = diff([], resting, BOT)
    assert cancel == []                                      # I1 immunity


def spec_E2_unwanted_rungs_cancel_missing_rungs_create():
    desired = [_desired(3, 53000.0, 0.008)]
    resting = [_resting(9, 59000.0, 0.008)]
    cancel, create = diff(desired, resting, BOT)
    assert [o['link_id'] for o in cancel] == [make_link(BOT, 9, 'a1')]
    assert create == desired


def spec_E2_duplicates_on_one_rung_keep_exactly_one():
    desired = [_desired(3, 53000.0, 0.008)]
    resting = [_resting(3, 53000.0, 0.008, gen='a1'),
               _resting(3, 53000.0, 0.008, gen='a2'),
               _resting(3, 53000.0, 0.008, gen='a3')]
    cancel, create = diff(desired, resting, BOT)
    assert len(cancel) == 2 and create == []                 # self-heals


def spec_E2_truncation_is_kept_but_a_grown_position_is_recovered():
    """The old spec pinned keeping a 0.009 exit against a 0.021 desire
    forever — conflating venue truncation with a position that GREW past
    a stale cover (audit 2026-08-07 wrong-spec). Small shrink: keep.
    Below three quarters: re-size, or the growth never exits."""
    want = _desired(12, 63000.0, 0.021, side='Sell', ro=True)
    shrunk = _resting(12, 63000.0, 0.019, side='Sell', ro=True)
    cancel, create = diff([want], [shrunk], BOT)
    assert cancel == [] and create == []          # venue-shrunk: keep
    stale = _resting(12, 63000.0, 0.009, side='Sell', ro=True)
    cancel, create = diff([want], [stale], BOT)
    assert len(cancel) == 1 and len(create) == 1  # grown past it: re-size
    oversized = _resting(12, 63000.0, 0.030, side='Sell', ro=True)
    cancel, create = diff([want], [oversized], BOT)
    assert len(cancel) == 1 and len(create) == 1  # over-covering: replace


def spec_E2_entry_qty_uses_relative_tolerance():
    want = _desired(3, 53000.0, 0.008)
    assert matches(want, _resting(3, 53000.0, 0.0079))       # within 5%
    assert not matches(want, _resting(3, 53000.0, 0.006))    # outside


# --- amend pairing: qty yes, price never -------------------------------------

def spec_E2_same_price_qty_change_is_an_amend():
    cancel = [_resting(3, 53000.0, 0.010)]
    create = [_desired(3, 53000.0, 0.008)]
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert len(amends) == 1 and cancels == [] and creates == []
    old, new = amends[0]
    assert old['qty'] == 0.010 and new['qty'] == 0.008


def spec_E2_a_moved_price_is_never_amended():
    # the trail-shaped case that made v2's spec vacuous (audit 3.8): same rung,
    # new price MUST cancel+create — amending price would jump the book queue
    cancel = [_resting(3, 53000.0, 0.008)]
    create = [_desired(3, 53500.0, 0.008)]
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert amends == [] and len(cancels) == 1 and len(creates) == 1


def spec_E2_amend_never_crosses_sides_or_flags():
    cancel = [_resting(3, 53000.0, 0.008, side='Sell', ro=True)]
    create = [_desired(3, 53000.0, 0.010)]
    amends, cancels, creates = pair_amends(cancel, create, BOT)
    assert amends == []


# --- E6/E7: the reaction matrix ----------------------------------------------

def spec_E7_every_kind_reacts_and_none_kills():
    assert set(KIND_REACTIONS) == set(KINDS)
    assert all('kill' not in r for r in KIND_REACTIONS.values())
    assert KIND_REACTIONS['margin'] == 'backoff_growth_only'
    assert KIND_REACTIONS['gone'] == 'treat_done'
