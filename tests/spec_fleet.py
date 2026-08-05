# Specs for SPEC F1-F6 — coverage both ways, the lock, snapshots incl. the
# dead, the mainnet absence, the watchdog's own validator and transitions.

import tempfile

from gridgremlin.config import ConfigError
from gridgremlin.main import (acquire_fleet_lock, check_watchdog_coverage,
                              refuse_mainnet, snapshot_row)
from gridgremlin.watchdog import (decide, evaluate, peak_equity,
                                  validate_watchdog)

WD = {'tag': 't', 'snapshot': 's.jsonl', 'state': 'st.json',
      'staleness_seconds': 1000, 'mm_rate_max': 0.5, 'equity_min': 1000,
      'equity_drawdown_max': 0.25, 're_alert_seconds': 1800,
      'assumes_sole_actor': True,
      'positions': {'botA': {'min': 0, 'max': 12.0}}}


def _wd(**over):
    d = dict(WD)
    d.update(over)
    return validate_watchdog(d)


def _refused(fn, *args, frag=''):
    try:
        fn(*args)
    except ConfigError as e:
        assert frag in str(e), str(e)
        return
    raise AssertionError(f'accepted, expected refusal with {frag!r}')


# --- F1: coverage, both ways -------------------------------------------------

def spec_F1_an_unwatched_bot_refuses_the_fleet():
    _refused(check_watchdog_coverage, [('botB', 10.0)], _wd(),
             frag='nothing trades unwatched')


def spec_F1_a_stale_watchdog_entry_also_refuses():
    _refused(check_watchdog_coverage, [], _wd(), frag='stale entry')


# --- F2: ceilings pinned near the cap ----------------------------------------

def spec_F2_a_decorative_ceiling_refuses():
    _refused(check_watchdog_coverage, [('botA', 2.0)], _wd(),
             frag='cap itself failed')       # 12.0 vs cap 2.0: decorative
    _refused(check_watchdog_coverage, [('botA', 20.0)], _wd(),
             frag='cap itself failed')       # 12.0 below cap 20.0: absurd
    check_watchdog_coverage([('botA', 10.0)], _wd())   # 12.0 in [10, 15]: fine


def spec_F2_martingales_skip_the_cap_check_but_not_coverage():
    check_watchdog_coverage([('botA', None)], _wd())


# --- F3: one fleet process per account ---------------------------------------

def spec_F3_the_second_process_refuses():
    with tempfile.NamedTemporaryFile() as f:
        first = acquire_fleet_lock(f.name)
        _refused(acquire_fleet_lock, f.name, frag='one fleet per account')
        first.close()
        acquire_fleet_lock(f.name).close()   # released -> acquirable again


# --- F4: the dead are visible ------------------------------------------------

class _DeadBot:
    botid, alive, _last_pos = 'botA', False, 0.0


class _LiveBot:
    botid, alive, _last_pos = 'botB', True, 0.021


def spec_F4_snapshots_include_dead_bots():
    row = snapshot_row([_DeadBot(), _LiveBot()],
                       {'equity': 5000.0, 'mm_rate': 0.01}, now=123.0)
    assert row['bots']['botA'] == {'alive': False, 'position': 0.0}
    assert row['bots']['botB']['alive'] is True


def spec_F4_dead_but_present_is_not_missing():
    cfg = _wd()
    row = {'t': 100.0, 'equity': 5000.0, 'mm_rate': 0.01,
           'bots': {'botA': {'alive': False, 'position': 0.0}}}
    assert 'missing:botA' not in evaluate(cfg, row, now=100.0, peak=5000.0)
    gone = dict(row, bots={})
    assert 'missing:botA' in evaluate(cfg, gone, now=100.0, peak=5000.0)


# --- F7 (D25): mainnet is double-safetied ------------------------------------

def spec_F7_mainnet_needs_both_safeties():
    class _Client:
        env = 'mainnet'
    _refused(refuse_mainnet, _Client(), frag='double-safetied')
    try:
        refuse_mainnet(_Client(), fleet_allows=True)      # file alone: refuse
    except Exception as e:
        assert '--allow-mainnet' in str(e)
    else:
        raise AssertionError('the fleet file alone armed mainnet')
    try:
        refuse_mainnet(_Client(), run_allows=True)        # launch alone: refuse
    except Exception as e:
        assert 'allow_mainnet' in str(e)
    else:
        raise AssertionError('the launch flag alone armed mainnet')
    refuse_mainnet(_Client(), fleet_allows=True, run_allows=True)  # both: fires


def spec_F7_demo_and_testnet_never_consult_the_safeties():
    class _Demo:
        env = 'demo'
    refuse_mainnet(_Demo())                               # no safeties needed


# --- F6 and the watchdog's own validator -------------------------------------

def spec_F6_the_assumption_set_is_typed_not_prose():
    bare = dict(WD)
    del bare['assumes_sole_actor']
    _refused(validate_watchdog, bare, frag='assumes_sole_actor')


def spec_watchdog_config_is_refused_like_everything_else():
    _refused(validate_watchdog, dict(WD, staleness_secondss=5),
             frag='unknown key')
    _refused(validate_watchdog, dict(WD, positions={}), frag='positions')


# --- evaluate: the breach set ------------------------------------------------

def _row(**over):
    row = {'t': 1000.0, 'equity': 5000.0, 'mm_rate': 0.1,
           'bots': {'botA': {'alive': True, 'position': 5.0}}}
    row.update(over)
    return row


def spec_evaluate_stale_mmr_equity_and_bounds():
    cfg = _wd()
    assert evaluate(cfg, None, 0, None) == {'nosnap': 'no readable snapshot row'}
    assert 'stale' in evaluate(cfg, _row(), now=2500.0, peak=5000.0)
    assert 'mmr' in evaluate(cfg, _row(mm_rate=0.6), 1000.0, 5000.0)
    assert 'equity' in evaluate(cfg, _row(equity=900.0), 1000.0, 5000.0)
    bots = {'botA': {'alive': True, 'position': 13.0}}
    assert 'pos:botA' in evaluate(cfg, _row(bots=bots), 1000.0, 5000.0)
    assert evaluate(cfg, _row(), 1000.0, 5000.0) == {}


def spec_evaluate_drawdown_measures_from_the_peak():
    cfg = _wd()
    assert 'drawdown' in evaluate(cfg, _row(equity=3000.0), 1000.0, peak=5000.0)
    assert 'drawdown' not in evaluate(cfg, _row(equity=4000.0), 1000.0, 5000.0)


def spec_peak_equity_none_is_unknown_never_zero():
    # v2's falsy sentinel silently disabled the drawdown check (M30)
    assert peak_equity(None, None) is None
    assert peak_equity(None, 5000.0) == 5000.0
    assert peak_equity(5000.0, None) == 5000.0
    assert peak_equity(5000.0, 6000.0) == 6000.0
    assert peak_equity(6000.0, 5000.0) == 6000.0       # monotone


# --- decide: page, remind, recover -------------------------------------------

def spec_decide_pages_new_reminds_on_interval_announces_recovery():
    pages, state = decide({}, {'mmr': 'x'}, now=0.0, re_alert_seconds=1800)
    assert pages == ['mmr: x']
    pages, state = decide(state, {'mmr': 'x'}, now=60.0, re_alert_seconds=1800)
    assert pages == []                                  # inside the interval
    pages, state = decide(state, {'mmr': 'x'}, now=1900.0, re_alert_seconds=1800)
    assert pages == ['still breached — mmr: x']
    pages, state = decide(state, {}, now=2000.0, re_alert_seconds=1800)
    assert pages == ['recovered: mmr'] and state == {}


# --- E7 at the loop: a failed read costs a cycle, never the process ----------
# Two overnight TLS resets each killed the HL unit (2026-08-05); systemd
# restarted it, but a restart resets in-memory state and fires the alarm.

def spec_E7_a_failed_read_costs_a_cycle_never_the_process():
    from gridgremlin import main as m
    from gridgremlin.events import Notifier
    calls = {'n': 0}

    class Flaky:
        env = 'demo'

        def read_wallet(self):
            calls['n'] += 1
            if calls['n'] == 2:
                raise OSError('[Errno 104] Connection reset by peer')
            return {'equity': 1000.0, 'mm_rate': 0.01}

    class IdleBot:
        alive = True
        cfg = {'venue': 'bybit'}
        botid = 'idle'

        def cycle(self, equity=None):
            return None

    events = []
    saved = (m.build_fleet, m.make_notifier, m.load_env, m.acquire_fleet_lock)
    m.build_fleet = lambda p, notif, **kw: ({'notify_orders': False,
                                             'poll_seconds': 0},
                                            {'bybit': Flaky()}, [IdleBot()])
    m.make_notifier = lambda: Notifier(sink=events.append)
    m.load_env = lambda: None
    m.acquire_fleet_lock = lambda path: open('/dev/null')
    try:
        rc = m.run('ignored', cycles=3, poll_seconds=0)
    finally:
        m.build_fleet, m.make_notifier, m.load_env, m.acquire_fleet_lock = saved
    assert rc == 0 and calls['n'] == 3             # cycle 2 lost, 3 still ran
    assert any('cycle 1 lost' in e for e in events)
    assert any('readable again after 1' in e for e in events)


def spec_F5_no_repo_fleet_file_ever_carries_the_mainnet_flag():
    import json
    from pathlib import Path
    configs = Path(__file__).resolve().parent.parent / 'configs'
    checked = 0
    for f in sorted(configs.glob('*.json')):
        data = json.loads(f.read_text())
        assert not (isinstance(data, dict) and data.get('allow_mainnet')), \
            f'{f.name} carries allow_mainnet — the armour ships OFF (F5/F7)'
        checked += 1
    assert checked >= 4                    # both fleets, both watchdogs
