# Specs for SPEC B2 and B1's naming — the split hysteresis, against the live
# churn shape slice 8 reproduced: a held rung, the mark wobbling across it.

from pathlib import Path

from gridgremlin.adapters import LinearAdapter
from gridgremlin.bot import Bot
from gridgremlin.config import validate_config
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


class WobbleVenue(FakeVenue):
    """A held lot at the 64,000 rung; the mark jitters across it — the
    suppression prefix flips each crossing unless the ref is held still."""

    def __init__(self):
        super().__init__(mark=64010.0)
        self.position = {'positionIdx': 1, 'side': 'Buy', 'size': '0.007',
                         'avgPrice': '63000', 'leverage': '10',
                         'unrealisedPnl': '0'}


def _run_wobble(frac, cycles=12):
    venue, lines = WobbleVenue(), []
    cfg = _cfg(split_hysteresis_rungs=frac) if frac is not None else _cfg()
    bot = Bot(cfg, ADAPTER, venue, Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()                                   # initial ladder
    baseline = len(venue.orders)
    ops = 0
    for i in range(cycles):
        venue.mark = 64010.0 if i % 2 == 0 else 63990.0    # +-10 across the rung
        before = len(lines)
        bot.cycle()
        ops += sum(1 for ln in lines[before:]
                   if ' placed ' in ln or ' cancel ' in ln)
    return ops, baseline, bot


# --- B2: quiet with the band on, churning with it off ------------------------

def spec_B2_the_wobble_fixture_is_quiet_with_the_band_on():
    ops, baseline, _ = _run_wobble(0.25)
    assert baseline > 0 and ops == 0              # the slice-8 churn, cured


def spec_B2_and_churns_with_it_off():
    ops, _, _ = _run_wobble(None)
    assert ops > 0                                # the guard is load-bearing


def spec_B2_zero_is_identical_to_unset():
    ops_zero, _, _ = _run_wobble(0.0)
    ops_none, _, _ = _run_wobble(None)
    assert ops_zero == ops_none                   # deploying it changes nothing


def spec_B2_the_ref_snaps_past_the_band_never_walks():
    venue, lines = WobbleVenue(), []
    bot = Bot(_cfg(split_hysteresis_rungs=0.3), ADAPTER, venue,
              Notifier(sink=lines.append), gen_seed=1)
    bot.cycle()
    held0 = bot._held_ref
    venue.mark = held0 + 100.0                    # inside the 300 band: holds
    bot.cycle()
    assert bot._held_ref == held0
    venue.mark = held0 + 400.0                    # past the band: snaps
    bot.cycle()
    assert abs(bot._held_ref - (held0 + 400.0)) < 1.0
    venue.mark = held0 + 800.0                    # a trend keeps releasing
    bot.cycle()
    assert abs(bot._held_ref - (held0 + 800.0)) < 1.0


def spec_W2_the_window_shares_the_held_anchor():
    # one anchor for plan AND window: while the ref is held, a wobble cannot
    # pull the window edge across a rung either — zero placement churn at the
    # window boundary (v2's audit-3.4 raw-vs-sticky split, closed).
    ops, _, bot = _run_wobble(0.25, cycles=20)
    assert ops == 0 and bot._held_ref is not None


# --- B1: the naming rule, mechanically ---------------------------------------

def spec_B1_deadband_appears_nowhere_in_the_engine():
    for name in ('bot.py', 'ladder.py', 'window.py', 'apply.py', 'events.py'):
        src = Path(f'gridgremlin/{name}').read_text()
        assert 'deadband' not in src, f'unqualified band word in {name}'
        assert 'hysteresis' not in src.replace('split_hysteresis_rungs', ''), (
            f'unqualified hysteresis in {name}')
