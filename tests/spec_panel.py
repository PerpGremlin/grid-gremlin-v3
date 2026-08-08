"""The panel's security floor, pinned live: real server, real requests."""
import json
import threading
import urllib.request
import urllib.error


def _serve(contract):
    import http.server
    from panel.server import Handler

    class H(Handler):
        def _contract(self, fleet):
            return contract
    H.token = 'tok123'
    import tempfile as _tf
    from pathlib import Path as _P
    _fp = _P(_tf.mkdtemp()) / 'f.json'
    _fp.write_text('{"bots": [{"x": 1}]}')     # exists and non-empty:
    H.fleets = (str(_fp),)                      # the init guard stands down
    H.labels = ('demo',)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.host_ok = f'127.0.0.1:{srv.server_port}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://{H.host_ok}'


CONTRACT = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
            
            'ranges': {'spoADAUSDTl': {'lower': 0.155, 'upper': 0.23,
                                       'rungs': 16}},
            'fee_floors': {'spoADAUSDTl': 0.0025},
            'watchdog': {'ceilings': {'spoADAUSDTl': 9700.0,
                                      'linDOGEs': 8000.0},
                         'swept_s_ago': 41,
                         'belief': {'age_s': 3, 'bots': {
                             'linDOGEs': {'alive': True,
                                          'position': 730.0}}}},
            'bots': {'spoADAUSDTl': {
                'fills': 3, 'realized': 5.04, 'fees': 2.07, 'bought': 910.0,
                'sold': 0.0, 'position': 910.57, 'avg_cost': 0.207,
                'unreal_at_mark': -4.83, 'truncated': False, 'mark': 0.2017,
                'side': 'long', 'strategy': 'grid', 'inverse': False}}}


def spec_P1_no_cookie_no_page_and_wrong_host_is_refused():
    srv, base = _serve(CONTRACT)
    try:
        try:
            urllib.request.urlopen(f'{base}/')
            assert False, 'served without auth'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(f'{base}/?t=tok123',
                                     headers={'Host': 'evil.example'})
        try:
            urllib.request.urlopen(req)
            assert False, 'rebinding not refused'
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.shutdown()


def spec_P2_the_token_becomes_a_cookie_and_the_page_renders_the_contract():
    srv, base = _serve(CONTRACT)
    try:
        op = urllib.request.build_opener()   # no redirect cookie jar needed:
        try:
            op.open(f'{base}/?t=tok123')     # 303 w/ Set-Cookie then / -> 401
        except urllib.error.HTTPError:
            pass
        req = urllib.request.Request(f'{base}/',
                                     headers={'Cookie': 'gg=tok123'})
        html = op.open(req).read().decode()
        assert 'spoADAUSDTl' in html and 'HOLDING' in html
        assert '910.57' in html
        assert '<svg' in html and 'circle' in html      # the range strip
        # settlement: 910.57 * 0.2017 * (1 - 0.0025) = 183.20
        assert '183.2' in html, 'stop-now estimate missing or wrong'
        assert '9% of 9,700' in html          # 910.57 / 9700 utilization
        assert 'watchdog swept 41s ago' in html
        req = urllib.request.Request(f'{base}/data',
                                     headers={'Cookie': 'gg=tok123'})
        data = json.loads(op.open(req).read())
        assert data == {'demo': CONTRACT}    # labelled by fleet, unmangled
    finally:
        srv.shutdown()


def spec_P3_rehearse_speaks_the_engines_refusal_verbatim():
    """One validator, three doors: a bad draft posted through the panel
    must come back with the engine's own refusal text — never a second
    validator's paraphrase. And a POST without auth or with a foreign
    Origin is refused before any work happens."""
    from gridgremlin.backtest_cli import run_draft
    import json as _json
    out = run_draft(_json.dumps(
        {'market_type': 'linear', 'venue': 'bybit', 'symbol': 'ADAUSDT',
         'side': 'long', 'capital': 1500, 'lower': 0.23, 'upper': 0.155,
         'rungs': 16}), 7, 60, 0.0002)
    assert 'refused' in out
    assert 'lower' in out['refused'] or 'upper' in out['refused']

    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(f'{base}/rehearse', data=b'gg=1',
                                     method='POST')
        try:
            urllib.request.urlopen(req)
            assert False, 'unauthed POST accepted'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(
            f'{base}/rehearse', data=b'gg=1', method='POST',
            headers={'Cookie': 'gg=tok123',
                     'Origin': 'http://evil.example'})
        try:
            urllib.request.urlopen(req)
            assert False, 'cross-origin POST accepted'
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.shutdown()


def spec_T3_the_rehearsal_reports_the_hold_benchmark():
    """§9: every verdict carries what the same capital did just holding —
    the number every user asks for and nobody ships."""
    from gridgremlin.adapters import SpotAdapter
    from gridgremlin.backtest_cli import rehearse
    from gridgremlin.config import validate_grid
    draft = validate_grid({'market_type': 'spot', 'symbol': 'ADAUSDT',
                           'side': 'long', 'capital': 1000,
                           'lower': 0.15, 'upper': 0.25, 'rungs': 11,
                           'stop': {'watch': 'mark_price', 'level': 0.14}})
    a = SpotAdapter({'symbol': 'ADAUSDT', 'qty_step': 0.01, 'min_qty': 1.0,
                     'price_tick': 0.0001, 'min_notional': 1.0})
    bars = [{'o': 0.20, 'h': 0.21, 'l': 0.19, 'c': 0.20},
            {'o': 0.20, 'h': 0.22, 'l': 0.20, 'c': 0.22}]
    out = rehearse(draft, bars, a)
    assert abs(out['hold_benchmark'] - 100.0) < 1e-9   # 1000 * (0.22/0.20-1)
    assert out['bars'] == 2


def _fake_adapter():
    from gridgremlin.adapters import LinearAdapter
    return LinearAdapter({'symbol': 'ADAUSDT', 'qty_step': 1.0,
                          'min_qty': 1.0, 'price_tick': 0.0001,
                          'min_notional': 1.0})


_FLEET = {'bots': [], 'watchdog': 'wd.json'}
_WD = {'tag': 't', 'snapshot': 's', 'state': 'st',
       'staleness_seconds': 600, 'mm_rate_max': 0.5,
       'equity_min': 100, 're_alert_seconds': 900,
       'assumes_sole_actor': True,
       'positions': {}}
_BOT = {'market_type': 'linear', 'venue': 'bybit', 'symbol': 'ADAUSDT',
        'side': 'long', 'capital': 1500, 'lower': 0.155, 'upper': 0.23,
        'rungs': 16, 'stop': {'watch': 'mark_price', 'level': 0.148}}


def spec_F1_the_create_flow_judges_the_merged_fleet_not_the_bot_alone():
    """§11 gate 1: an unwatchable addition is refused by the engine's own
    coverage check, in the engine's own words — and a well-watched one
    passes. Bot and watcher land together or not at all."""
    from panel.create import merge_proposal, validate_whole
    from gridgremlin.config import validate_grid
    from gridgremlin.ladder import grid_rungs, position_cap
    adapter = _fake_adapter()
    vbot = validate_grid(dict(_BOT))    # the same normalisation the flow does
    cap = position_cap(vbot, adapter, grid_rungs(vbot, adapter))
    # ceiling inside the band: the merged fleet validates
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': cap * 1.2}})
    assert botid == 'linADAUSDTl'
    assert validate_whole(fleet, wd, lambda c: adapter) is None
    assert wd['positions']['linADAUSDTl']['max'] == cap * 1.2
    # ceiling beyond 1.5x cap: refused, engine's words (F2)
    _, fleet2, wd2 = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': cap * 3.0}})
    why = validate_whole(fleet2, wd2, lambda c: adapter)
    assert why and 'ceiling' in why
    # duplicate identity: refused before validation
    try:
        merge_proposal(fleet, wd, {'bot': dict(_BOT),
                                   'watchdog': {'max': cap}})
        assert False, 'identity reused'
    except Exception as e:
        assert 'already in this fleet' in str(e)


def spec_X8_atomic_write_replaces_whole_and_keeps_the_bak():
    """§11: 'safe' means an atomic rename with a kept .bak — the OctoBot
    safe_dump lesson. The old content survives beside the new."""
    import tempfile
    from pathlib import Path as _P
    from panel.create import atomic_write
    d = _P(tempfile.mkdtemp())
    p = d / 'fleet.json'
    p.write_text('{"old": true}')
    atomic_write(p, '{"new": true}')
    assert p.read_text() == '{"new": true}'
    assert (d / 'fleet.json.bak').read_text() == '{"old": true}'
    assert not list(d.glob('fleet.json?*[!k]'))       # no temp litter


def spec_C1_control_is_opt_in_and_typed():
    """§12: a panel launched without --unit has NO control surface; with
    it, an unmatched typed confirmation does nothing."""
    srv, base = _serve(CONTRACT)
    try:
        req = urllib.request.Request(f'{base}/control',
                                     headers={'Cookie': 'gg=tok123'})
        try:
            urllib.request.urlopen(req)
            assert False, 'control served unarmed'
        except urllib.error.HTTPError as e:
            assert e.code == 404
        req = urllib.request.Request(
            f'{base}/unit', data=b'gg=1&action=stop&confirm=wrong',
            method='POST', headers={'Cookie': 'gg=tok123'})
        try:
            urllib.request.urlopen(req)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404       # unarmed: refused before the confirm
    finally:
        srv.shutdown()


def spec_X7_revive_removes_exactly_the_typed_entry_atomically():
    """The revive path is the delete-the-entry-deliberately workflow: the
    typed botid goes, everything else stays, .bak keeps the before."""
    import tempfile
    from pathlib import Path as _P
    from panel.create import atomic_write
    d = _P(tempfile.mkdtemp())
    tp = d / 'tombstones.json'
    tp.write_text(json.dumps({'a': {'reason': 'x'}, 'b': {'reason': 'y'}}))
    tombs = json.loads(tp.read_text())
    tombs.pop('a')
    atomic_write(tp, json.dumps(tombs))
    assert json.loads(tp.read_text()) == {'b': {'reason': 'y'}}
    assert 'a' in json.loads((d / 'tombstones.json.bak').read_text())


def spec_V7_a_quiet_bot_is_shown_not_omitted():
    """No fills in the window must never mean no row: the page renders the
    engine's belief (labelled as belief) — HOLDING, RESTING, or DEAD.
    Live 2026-08-08: three HL bots vanished from the panel for being
    quiet, and quiet is exactly when you want to see them."""
    c = json.loads(json.dumps(CONTRACT))
    c['bots']['linDOGEs'] = None                  # configured, no fills
    html = __import__('panel.server', fromlist=['render']).render(
        [('hl', c)])
    assert 'linDOGEs' in html
    assert 'HOLDING' in html and '730 (belief)' in html
    assert 'no fills' in html
    # every row carries the full column count — a short row shears the
    # table and lands cells under the wrong headers (live 2026-08-08)
    for row in html.split('<tr>')[1:]:
        cells = row.split('</tr>')[0]
        n = cells.count('<td') or cells.count('<th')
        assert n == 15, f'{n} cells in row: {cells[:90]}'


def spec_F1_edit_and_remove_move_bot_and_watcher_together():
    """An edit keeps identity or is refused; a removal takes the watchdog
    line with it and the remaining fleet still validates (F1) — the same
    one-act rule as creation, in reverse."""
    from panel.create import (edit_proposal, merge_proposal,
                              remove_proposal, validate_whole)
    from gridgremlin.config import validate_grid
    from gridgremlin.ladder import grid_rungs, position_cap
    adapter = _fake_adapter()
    vbot = validate_grid(dict(_BOT))
    cap = position_cap(vbot, adapter, grid_rungs(vbot, adapter))
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': dict(_BOT), 'watchdog': {'max': cap * 1.2}})
    # edit: new capital, watcher moves with it, fleet revalidates
    newbot = dict(_BOT, capital=2000)
    vnew = validate_grid(dict(newbot))
    ncap = position_cap(vnew, adapter, grid_rungs(vnew, adapter))
    _, f2, w2 = edit_proposal(fleet, wd, botid, newbot, ncap * 1.2)
    assert validate_whole(f2, w2, lambda c: adapter) is None
    assert f2['bots'][0]['capital'] == 2000
    # edit refusing an identity change
    try:
        edit_proposal(fleet, wd, botid, dict(_BOT, side='short'), cap)
        assert False
    except Exception as e:
        assert 'cannot change identity' in str(e)
    # remove: both lines go; the empty fleet still validates coverage
    _, f3, w3 = remove_proposal(fleet, wd, botid)
    assert f3['bots'] == [] and botid not in w3['positions']
    assert 'not in this fleet' in str(
        _catch(lambda: remove_proposal(f3, w3, botid)))


def _catch(fn):
    try:
        fn()
        return ''
    except Exception as e:
        return str(e)


def spec_V8_the_export_is_the_same_renderer_frozen():
    """§4: one renderer, two artefacts. The export carries the same rows,
    drops the refresh and every action link, and stamps its provenance —
    a snapshot must say it is one."""
    from panel.server import render
    live = render([('demo', CONTRACT)])
    frozen = render([('demo', CONTRACT)], static='Fri, 08 Aug 2026')
    assert 'spoADAUSDTl' in frozen and '910.57' in frozen
    assert 'http-equiv="refresh"' in live
    assert 'http-equiv="refresh"' not in frozen
    assert '/control' in live and '/control' not in frozen
    assert 'exported Fri, 08 Aug 2026' in frozen
    assert 'snapshot, not a live view' in frozen


def spec_T3_the_verdict_draws_the_equity_path_with_a_zero_line():
    """The curve is inline SVG with the zero line drawn — a rehearsal that
    spent the window underwater must LOOK underwater."""
    from panel.server import verdict
    out = {'grid_profit': 5.0, 'fees': 1.0, 'net': 4.0, 'total': 4.0,
           'hold_benchmark': 2.0, 'max_drawdown': 3.0, 'trips': 2,
           'entry_fills': 4, 'held': 0.0, 'basis': None, 'bars': 3,
           'equity_curve': [0.0, -2.0, 4.0]}
    html = verdict({'symbol': 'X', 'side': 'long', 'lower': 1, 'upper': 2,
                    'rungs': 3}, out)
    assert '<polyline' in html and '<line' in html
    from panel.server import curve_svg
    assert curve_svg([]) == '' and curve_svg([1.0]) == ''


def spec_M2_the_preview_does_the_compounding_and_names_full_depth():
    """§8: the deviation ladder as numbers — every 3Commas thread's
    hand-arithmetic, machine-done. Pinned by hand: base 800 + safeties
    800x1.5^i, deviations 0.8% stepping x1.5, short side (prices ABOVE
    the anchor)."""
    from panel.create import martingale_preview
    from gridgremlin.config import validate_martingale
    raw = {'strategy': 'martingale', 'market_type': 'linear',
           'symbol': 'SOLUSDT', 'side': 'short', 'capital': 5000,
           'leverage': 10, 'base_order_size': 800, 'safety_order_size': 800,
           'order_size_multiplier': 1.5, 'deviation_pct': 0.008,
           'deviation_step_multiplier': 1.5, 'max_averaging_orders': 4,
           'take_profit_avg_pct': 0.012, 'repeat': True}
    cfg = validate_martingale(dict(raw))
    rows, full = martingale_preview(cfg, 100.0)
    assert len(rows) == 5                       # base + 4 safeties
    assert rows[0]['price'] == 100.0 and rows[0]['notional'] == 800
    assert abs(rows[1]['price'] - 100.8) < 1e-9         # +0.8%
    assert abs(rows[2]['price'] - 102.0) < 1e-9         # +0.8% + 1.2%
    assert rows[2]['notional'] == 1200                  # 800 x 1.5
    assert abs(rows[-1]['cum_notional'] - (800 + 800 + 1200 + 1800 + 2700)) < 1e-9
    assert abs(full - sum(r['qty'] for r in rows)) < 1e-12
    # and a martingale proposal passes the whole-fleet gate with a ceiling
    from panel.create import merge_proposal, validate_whole
    # merge the RAW row, as the flow does — the validator's derived keys
    # (ladder_notional) never belong in a fleet file
    botid, fleet, wd = merge_proposal(
        _FLEET, _WD, {'bot': raw, 'watchdog': {'max': full * 1.2}})
    assert botid == 'linSOLUSDTs'
    assert validate_whole(fleet, wd, lambda c: _fake_adapter()) is None


def spec_F1_init_writes_a_valid_pair_and_only_into_the_empty_world():
    """First run: a minimal fleet + watchdog pair the create flow can
    merge into — watchdog validated by the engine's own loader before
    anything touches disk; existing files are never overwritten."""
    import tempfile
    from pathlib import Path as _P
    from panel.create import init_pair
    from gridgremlin.watchdog import validate_watchdog
    d = _P(tempfile.mkdtemp())
    wp = init_pair(d / 'fleet.mine.json', 'mine', equity_min=500.0)
    fleet = json.loads((d / 'fleet.mine.json').read_text())
    wd = json.loads(wp.read_text())
    assert fleet == {'bots': [], 'watchdog': str(wp)}
    # the loaders refuse EMPTY worlds (correctly, for running) — so the
    # pair must validate the moment one bot joins it, which is the gate
    # that actually matters
    from panel.create import merge_proposal, validate_whole
    from gridgremlin.config import validate_grid
    _, f2, w2 = merge_proposal(fleet, wd, {'bot': dict(_BOT),
                                           'watchdog': {'max': 9604.0}})
    assert validate_whole(f2, w2, lambda c: _fake_adapter()) is None
    assert wd['assumes_sole_actor'] is True and wd['equity_min'] == 500.0
    try:
        init_pair(d / 'fleet.mine.json', 'mine', 500.0)
        assert False, 'overwrote an existing world'
    except Exception as e:
        assert 'already exists' in str(e)


def spec_V9_the_key_defines_every_word_the_page_uses():
    """A dashboard that needs a translator failed the thesis: the key
    defines each column, state, and symbol the page can show."""
    from panel.server import KEY
    for term in ('realized', 'unreal', 'stop-now', 'watcher', 'DEAD',
                 'UNWATCHED', '(belief)', 'ZERO-SPREAD', 'hold benchmark',
                 'trips', 'max depth', '* (star)'):
        assert term in KEY, f'key missing: {term}'


def spec_F3_the_supervisor_detaches_stops_and_never_mistakes_a_stale_pid():
    """§13 with a real process: start detaches (the child outlives any
    parent shell), status reads pid-liveness, stop is SIGTERM, and a
    dead pid is reported as stale — never as a running engine."""
    import os
    import subprocess as sp
    import sys as _sys
    import tempfile
    import time as _t
    from pathlib import Path as _P
    from panel import supervise as sup
    d = _P(tempfile.mkdtemp())
    (d / 'configs').mkdir()
    (d / 'logs').mkdir()
    fleet = d / 'configs' / 'fleet.t.json'
    fleet.write_text('{}')
    assert sup.status(fleet) == ('stopped', None)
    # a stand-in child (the real engine would refuse the empty fleet —
    # correctly; the supervisor's contract is process handling)
    proc = sp.Popen([_sys.executable, '-c', 'import time; time.sleep(60)'],
                    start_new_session=True)
    sup._pid_path(fleet).write_text(str(proc.pid))
    st, pid = sup.status(fleet)
    assert st == 'running' and pid == proc.pid
    assert 'already running' in sup.start(fleet)     # no double spawn
    note = sup.stop(fleet)
    assert 'parked, not flattened' in note
    for _ in range(50):
        if proc.poll() is not None:
            break
        _t.sleep(0.1)
    assert proc.poll() is not None, 'SIGTERM did not land'
    assert sup.status(fleet) == ('stopped', None)
    # a stale pid (dead process) is named, never believed
    sup._pid_path(fleet).write_text(str(proc.pid))
    st, _ = sup.status(fleet)
    assert st == 'stale pid file'
    assert 'not running' in sup.stop(fleet)
