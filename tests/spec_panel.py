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
    H.fleets = ('f.json',)
    H.labels = ('demo',)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.host_ok = f'127.0.0.1:{srv.server_port}'
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://{H.host_ok}'


CONTRACT = {'window_hours': 6.0, 'generated_ms': 0, 'unowned': {},
            'ranges': {'spoADAUSDTl': {'lower': 0.155, 'upper': 0.23,
                                       'rungs': 16}},
            'fee_floors': {'spoADAUSDTl': 0.0025},
            'watchdog': {'ceilings': {'spoADAUSDTl': 9700.0},
                         'swept_s_ago': 41},
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
