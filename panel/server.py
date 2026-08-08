"""The panel, phase View — a localhost window onto the readout's contract.

Security floor (docs/DASHBOARD.md §5): binds 127.0.0.1 on a random port;
a per-launch token is exchanged for a cookie on first load; the exact Host
is allowlisted (defeats DNS rebinding); no CORS headers exist; keys do not
exist here — this process holds no secrets and can write nothing.

    python3 -m panel.server <fleet.json> [--hours N]

Data is the engine's own contract (report --json). One shape, every
renderer: this page can never disagree with the terminal readout.
"""
import http.server
from pathlib import Path
import urllib.parse
import json
import secrets
import subprocess
import sys
import time

REFRESH_S = 15          # the readout hits venue APIs: poll gently
CACHE_TTL_S = 10.0

CSS = """:root{--bg:#14161a;--fg:#d6dae0;--dim:#7a828c;--line:#262a30;
--pos:#5dbb7c;--neg:#d4756b;--accent:#8ab4d8}
:root.light{--bg:#f5f4f0;--fg:#232629;--dim:#6f6a60;--line:#ddd8d0;
--pos:#2e7d4f;--neg:#b04a40;--accent:#3a6ea5}
body{background:var(--bg);color:var(--fg);font:14px/1.5 monospace;margin:2em}
table{border-collapse:collapse;width:100%}td,th{padding:.35em .8em;
text-align:right;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:normal}td:first-child,th:first-child
{text-align:left}.pos{color:var(--pos)}.neg{color:var(--neg)}
.dim{color:var(--dim)}h1{font-size:1.1em;color:var(--accent)}
button{background:none;border:1px solid var(--line);color:var(--dim);
cursor:pointer;float:right}"""


def money(v, cls=True):
    if v is None:
        return '<td class="dim">—</td>'
    c = ' class="pos"' if (cls and v > 0) else (' class="neg"'
                                               if cls and v < 0 else '')
    return f'<td{c}>{v:,.2f}</td>'


def strip(rng, mark):
    """The range as a picture: bar, rung ticks, mark dot. Inline SVG,
    server-side, no scripts — a glance instead of arithmetic."""
    if not rng or not mark:
        return ''
    lo, hi = rng['lower'], rng['upper']
    span = hi - lo or 1.0
    x = max(0.0, min(1.0, (mark - lo) / span)) * 100
    ticks = ''.join(
        f'<line x1="{lo_x:.1f}" y1="3" x2="{lo_x:.1f}" y2="9" '
        'stroke="var(--line)"/>'
        for i in range(rng.get('rungs') or 0)
        for lo_x in [i / max(1, (rng['rungs'] - 1)) * 100])
    return (f'<svg width="120" height="12" viewBox="0 0 100 12" '
            f'preserveAspectRatio="none"><rect x="0" y="4" width="100" '
            f'height="4" fill="var(--line)"/>{ticks}'
            f'<circle cx="{x:.1f}" cy="6" r="3" fill="var(--accent)"/></svg>')


def settle(b, floor):
    """Stop now and you receive: the number every user reaches for and
    nobody ships. Position sold at mark, less the venue-shaped fee —
    an estimate and labelled as one."""
    if abs(b['position']) < 1e-12 or not b['mark'] or b.get('inverse'):
        return '<span class="dim">flat</span>'
    quote = abs(b['position']) * b['mark'] * (1.0 - (floor or 0.0))
    return f'~{quote:,.2f} quote'


def sweep_note(contract):
    wd = contract.get('watchdog') or {}
    ago = wd.get('swept_s_ago')
    if ago is None:
        return '<span class="neg">watchdog: never swept / unreadable</span>'
    cls = 'neg' if ago > 900 else 'dim'
    return f'<span class="{cls}">watchdog swept {ago}s ago</span>'


CREATE_FORM = """<h1>create a grid <span class="dim">— bot and watcher,
one act (§8). Four gates; nothing is written until you type the botid.
</span></h1><form method="post" action="/create">
<table><tr><th>symbol</th><th>side</th><th>lower</th><th>upper</th>
<th>rungs</th><th>capital</th><th>ceiling</th><th></th></tr>
<tr><td><input name="symbol" value="ADAUSDT" size="9"></td>
<td><select name="side"><option>long</option><option>short</option>
</select></td><td><input name="lower" size="8"></td>
<td><input name="upper" size="8"></td>
<td><input name="rungs" value="16" size="4"></td>
<td><input name="capital" value="1500" size="7"></td>
<td><input name="ceiling" size="8" placeholder="blank = cap x1.2"></td>
<td><button>run the gates</button></td></tr></table>
<input type="hidden" name="gg" value="1"></form>
<p class="dim">linear Bybit grids in this slice. The stop defaults to
mark_price 2% below the lower rung; edit the file for anything fancier —
same contract, other door.</p><p><a href="/">&larr; fleet</a></p>"""


FORM = """<h1>rehearse a grid <span class="dim">— a draft, validated by
the engine, replayed over real candles. nothing is created.</span></h1>
<form method="post" action="/rehearse">
<table><tr><th>symbol</th><th>side</th><th>lower</th><th>upper</th>
<th>rungs</th><th>capital</th><th>days</th><th></th></tr>
<tr><td><input name="symbol" value="ADAUSDT" size="9"></td>
<td><select name="side"><option>long</option><option>short</option></select>
</td><td><input name="lower" size="8"></td>
<td><input name="upper" size="8"></td>
<td><input name="rungs" value="16" size="4"></td>
<td><input name="capital" value="1500" size="7"></td>
<td><input name="days" value="7" size="4"></td>
<td><button>rehearse</button></td></tr></table>
<input type="hidden" name="gg" value="1"></form>
<p class="dim">linear Bybit grids only; a rehearsal is not a promise —
same candles are never same fills, and the replay plans without bid/ask
so guard-band drops never happen (slightly optimistic, stated per §9).</p>
<p><a href="/">&larr; fleet</a></p>"""


def verdict(draft, out):
    if 'refused' in out:
        return (f'{FORM}<h1 class="neg">the engine refuses this draft</h1>'
                f'<p class="neg">{out["refused"]}</p>')
    rows = ''.join(
        f'<tr><td>{k}</td>{money(v)}</tr>' for k, v in
        [('grid profit', out['grid_profit']), ('fees', -out['fees']),
         ('net', out['net']), ('total (incl. open)', out['total']),
         ('hold benchmark', out['hold_benchmark']),
         ('max drawdown', -out['max_drawdown'])])
    return (f"{FORM}<h1>{draft.get('symbol')} {draft.get('side')} "
            f"{draft.get('lower')}–{draft.get('upper')} x "
            f"{draft.get('rungs')} — {out['bars']} bars</h1>"
            f"<table>{rows}<tr><td>trips / entry fills</td>"
            f"<td>{out['trips']} / {out['entry_fills']}</td></tr>"
            f"<tr><td>ends holding</td><td>{out['held']:.10g}"
            + (f" @ {out['basis']:,.6g}" if out.get('basis') else '')
            + "</td></tr></table>"
            "<p class='dim'>window shown, never annualised. beat the hold "
            "benchmark or hold.</p>")


def render(contract):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    rows = []
    for botid, b in contract['bots'].items():
        state = ('HOLDING' if abs(b['position']) > 1e-12 else 'FLAT')
        openat = (f"{b['position']:.10g} @ {b['avg_cost']:.6g}"
                  if abs(b['position']) > 1e-12 else '—')
        total = (b['realized'] - b['fees']
                 + (b['unreal_at_mark'] or 0.0))
        note = ' *' if b['truncated'] else ''
        rng = contract.get('ranges', {}).get(botid)
        floor = contract.get('fee_floors', {}).get(botid)
        wd = contract.get('watchdog') or {}
        ceil = (wd.get('ceilings') or {}).get(botid)
        if ceil:
            used = abs(b['position']) / ceil * 100
            wcls = ' class="neg"' if used >= 100 else ''
            watch = f'<td{wcls}>{used:.0f}% of {ceil:,.4g}</td>'
        else:
            watch = '<td class="neg">UNWATCHED</td>'
        edge = ''
        if rng and b['mark']:
            edge = (f"<td>{strip(rng, b['mark'])}</td>"
                    f"<td class='dim'>{(b['mark'] - rng['lower']) / b['mark'] * 100:.1f}%"
                    f" / {(rng['upper'] - b['mark']) / b['mark'] * 100:.1f}%</td>")
        else:
            edge = '<td class="dim">—</td><td class="dim">—</td>'
        rows.append(
            f'<tr><td>{botid}{note}</td><td class="dim">{state}</td>'
            f"<td>{b['fills']}</td>{money(b['realized'])}"
            f"{money(b['fees'], cls=False)}<td>{openat}</td>"
            f"{money(b['unreal_at_mark'])}{money(total)}"
            f"<td>{b['bought']:,.4g}</td><td>{b['sold']:,.4g}</td>"
            f"{edge}<td>{settle(b, floor)}</td>{watch}</tr>")
    return f"""<!doctype html><meta charset="utf-8">
<title>grid-gremlin</title><style>{CSS}</style>
<meta http-equiv="refresh" content="{REFRESH_S}">
<button onclick="document.documentElement.classList.toggle('light')">
theme</button>
<h1>grid-gremlin — last {contract['window_hours']:g}h {sweep_note(contract)}
<span class="dim">(read {age}s ago; refreshes every {REFRESH_S}s)</span></h1>
<table><tr><th>bot</th><th>state</th><th>fills</th><th>realized</th>
<th>fees</th><th>open@avg</th><th>unreal</th><th>total</th>
<th>bought</th><th>sold</th><th>range</th><th>edge lo/hi</th>
<th>stop-now est.</th><th>watcher</th></tr>{''.join(rows)}</table>
<p><a href="/rehearse">rehearse a draft grid &rarr;</a> ·
<a href="/create">create a grid &rarr;</a> ·
<a href="/control">control &rarr;</a></p>
<p class="dim">stop-now est. = position at mark less the venue fee floor —
an estimate, not a promise; the venue settles what it settles.<br>
* window opened mid-round: partial numbers (R7).
This page renders the engine's own readout contract — it cannot disagree
with the terminal. It holds no keys and can write nothing.</p>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'gg-panel'
    token = ''
    unit = None            # §12: control is opt-in per launch (--unit)
    host_ok = ''
    fleet = ''
    hours = 24.0
    _cache = (0.0, None)

    def log_message(self, *a):
        pass

    def _contract(self):
        t, data = Handler._cache
        if data is not None and time.time() - t < CACHE_TTL_S:
            return data
        out = subprocess.run(
            [sys.executable, '-m', 'gridgremlin.report', self.fleet,
             '--hours', str(self.hours), '--json'],
            capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout)
        Handler._cache = (time.time(), data)
        return data

    def _authed(self):
        return f'gg={self.token}' in (self.headers.get('Cookie') or '')

    def _deny(self, code, why):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(why.encode())

    def do_GET(self):
        if self.headers.get('Host', '') != self.host_ok:
            return self._deny(403, 'wrong Host')       # rebinding defence
        if self.path.startswith('/?t='):
            if secrets.compare_digest(self.path[4:], self.token):
                self.send_response(303)
                self.send_header('Set-Cookie',
                                 f'gg={self.token}; HttpOnly; SameSite=Strict')
                self.send_header('Location', '/')
                self.end_headers()
                return
            return self._deny(403, 'bad token')
        if not self._authed():
            return self._deny(401, 'open the tokened URL from the terminal')
        if self.path == '/control':
            return self._control_page()
        if self.path == '/create':
            return self._page(CREATE_FORM)
        if self.path == '/rehearse':
            body = (f'<!doctype html><meta charset="utf-8">'
                    f'<title>rehearse</title><style>{CSS}</style>{FORM}')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body.encode())
            return
        body = (json.dumps(self._contract()) if self.path == '/data'
                else render(self._contract()))
        self.send_response(200)
        self.send_header('Content-Type',
                         'application/json' if self.path == '/data'
                         else 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body.encode())


    def do_POST(self):
        if self.headers.get('Host', '') != self.host_ok:
            return self._deny(403, 'wrong Host')
        if not self._authed():
            return self._deny(401, 'open the tokened URL from the terminal')
        origin = self.headers.get('Origin', '')
        if origin and origin != f'http://{self.host_ok}':
            return self._deny(403, 'wrong Origin')     # cross-site write
        raw = self.rfile.read(min(int(self.headers.get(
            'Content-Length') or 0), 16384)).decode()
        form = dict(urllib.parse.parse_qsl(raw))
        if form.pop('gg', None) != '1':
            return self._deny(403, 'missing form token')
        if self.path in ('/create', '/apply'):
            return self._create_flow(form, apply=self.path == '/apply')
        if self.path in ('/unit', '/revive'):
            return self._control_act(form, self.path)
        if self.path != '/rehearse':
            return self._deny(404, 'no such action')
        draft = {'market_type': 'linear', 'venue': 'bybit',
                 'symbol': form.get('symbol', '').upper(),
                 'side': form.get('side', 'long'),
                 'capital': _f(form.get('capital')),
                 'lower': _f(form.get('lower')),
                 'upper': _f(form.get('upper')),
                 'rungs': int(_f(form.get('rungs')) or 0)}
        out = subprocess.run(
            [sys.executable, '-m', 'gridgremlin.backtest_cli', '--draft',
             '--days', form.get('days', '7')],
            input=json.dumps(draft), capture_output=True, text=True,
            timeout=120, cwd=None)
        result = json.loads(out.stdout or '{"refused": "the rehearsal '
                            'process died — see the panel journal"}')
        body = (f'<!doctype html><meta charset="utf-8"><title>rehearse'
                f'</title><style>{CSS}</style>{verdict(draft, result)}')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body.encode())


    def _page(self, body):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write((f'<!doctype html><meta charset="utf-8">'
                          f'<title>create</title><style>{CSS}</style>'
                          + body).encode())

    def _create_flow(self, form, apply=False):
        from panel.create import (CEILING_PREFILL, atomic_write, dry_ladder,
                                  merge_proposal, public_adapter,
                                  public_mark, unified_diff, validate_whole)
        from gridgremlin.ladder import grid_rungs, position_cap
        fleet_p = Path(self.fleet)
        fleet_raw = json.loads(fleet_p.read_text())
        wd_p = Path(fleet_raw['watchdog'])
        wd_raw = json.loads(wd_p.read_text())
        if apply:
            proposal = json.loads(form.get('proposal', '{}'))
        else:
            lo = _f(form.get('lower'))
            bot = {'market_type': 'linear', 'venue': 'bybit',
                   'symbol': form.get('symbol', '').upper(),
                   'side': form.get('side', 'long'),
                   'capital': _f(form.get('capital')),
                   'lower': lo, 'upper': _f(form.get('upper')),
                   'rungs': int(_f(form.get('rungs')) or 0),
                   'stop': {'watch': 'mark_price',
                            'level': round((lo or 0) * 0.98, 10)}}
            proposal = {'bot': bot, 'watchdog': {'max': _f(form.get('ceiling'))}}
        try:
            from gridgremlin.config import validate_grid
            vbot = validate_grid(dict(proposal['bot']))   # raw dicts lack
            adapter = public_adapter(vbot)                # defaults (A1)
            if proposal['watchdog'].get('max') is None:
                cap = position_cap(vbot, adapter, grid_rungs(vbot, adapter))
                proposal['watchdog']['max'] = round(cap * CEILING_PREFILL, 6)
            botid, fleet, wd = merge_proposal(fleet_raw, wd_raw, proposal)
            refusal = validate_whole(fleet, wd, lambda cfg: adapter
                                     if cfg is proposal['bot']
                                     else public_adapter(cfg))
        except Exception as e:                              # noqa: BLE001
            return self._page(f'{CREATE_FORM}<h1 class="neg">refused</h1>'
                              f'<p class="neg">{e}</p>')
        if refusal:
            return self._page(f'{CREATE_FORM}<h1 class="neg">the engine '
                              f'refuses this fleet</h1>'
                              f'<p class="neg">{refusal}</p>')
        new_fleet = json.dumps(fleet, indent=1) + '\n'
        new_wd = json.dumps(wd, indent=1) + '\n'
        if apply:
            if form.get('confirm', '') != botid:
                return self._page('<h1 class="neg">not applied</h1><p>the '
                                  f'typed confirmation must be exactly '
                                  f'<b>{botid}</b> — a click is not a '
                                  'decision (§11). <a href="/create">back'
                                  '</a></p>')
            atomic_write(fleet_p, new_fleet)
            atomic_write(wd_p, new_wd)
            return self._page(f'<h1>{botid}: written</h1><p>bot and watcher '
                              'landed together; .bak kept beside each file. '
                              '<b>The fleet trades the old config until you '
                              'restart it</b> — enacting is phase 3\'s job '
                              '(§11).</p><p><a href="/">fleet</a></p>')
        mark = public_mark(vbot)
        ladder = dry_ladder(vbot, adapter, mark)
        rows = ''.join(f"<tr><td>{o['side']}</td><td>{o['price']:,.6g}</td>"
                       f"<td>{o['qty']:,.6g}</td></tr>" for o in ladder)
        diffs = (unified_diff(fleet_p.read_text(), new_fleet, fleet_p.name)
                 + unified_diff(wd_p.read_text(), new_wd, wd_p.name))
        pj = json.dumps(proposal).replace('"', '&quot;')
        return self._page(
            f'<h1>{botid} — gates 1-3 passed</h1>'
            f'<h1 class="dim">the diff</h1><pre class="dim">{diffs}</pre>'
            f'<h1 class="dim">the ladder at mark {mark:,.6g} (dry-run — '
            f'nothing placed)</h1><table><tr><th>side</th><th>price</th>'
            f'<th>qty</th></tr>{rows}</table>'
            f'<form method="post" action="/apply">'
            f'<input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="proposal" value="{pj}">'
            f'type the botid to write the files: '
            f'<input name="confirm" size="16" placeholder="{botid}">'
            f'<button>apply</button></form>'
            f'<p class="dim">apply writes files only; the running fleet is '
            f'untouched until restarted (§11).</p>')


    def _tombs_path(self):
        return Path(self.fleet).parent.parent / 'logs' / 'tombstones.json'

    def _control_page(self):
        if not self.unit:
            return self._deny(404, 'control is not armed on this panel '
                                   '(start it with --unit) — §12')
        state = subprocess.run(['systemctl', '--user', 'is-active',
                                self.unit], capture_output=True,
                               text=True).stdout.strip()
        cls = 'pos' if state == 'active' else 'neg'
        tombs = {}
        tp = self._tombs_path()
        if tp.exists():
            tombs = json.loads(tp.read_text() or '{}')
        trows = ''.join(
            f"<tr><td>{b}</td><td class='dim'>{v.get('reason')}</td>"
            f"<td><form method='post' action='/revive' style='margin:0'>"
            f"<input type='hidden' name='gg' value='1'>"
            f"<input name='confirm' size='14' placeholder='{b}'>"
            f"<button>revive</button></form></td></tr>"
            for b, v in tombs.items()) or             '<tr><td class="dim" colspan="3">no tombstones</td></tr>'
        body = f"""<h1>control <span class="dim">— processes and files,
never the venue (§12)</span></h1>
<p>fleet unit <b>{self.unit}</b>: <span class="{cls}">{state}</span></p>
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>restart</option><option>stop</option>
<option>start</option></select>
type the unit name to confirm: <input name="confirm" size="22"
placeholder="{self.unit}"><button>do it</button></form>
<p class="dim">stop PARKS, never flattens: positions and their
venue-resting orders survive a stopped engine (E3) — but stops go
unevaluated and nothing replenishes until start. restart enacts any
written config (§11).</p>
<h1>tombstones <span class="dim">— revival is deliberate, with the
evidence (X7)</span></h1>
<table><tr><th>bot</th><th>reason</th><th></th></tr>{trows}</table>
<p class="dim">a revival takes effect at the next fleet start — the
file is the truth; the process reads it at build.</p>
<p><a href="/">&larr; fleet</a></p>"""
        return self._page(body)

    def _control_act(self, form, path):
        if not self.unit:
            return self._deny(404, 'control is not armed on this panel')
        if path == '/unit':
            if form.get('confirm', '') != self.unit:
                return self._page('<h1 class="neg">not done</h1><p>type the '
                                  f'unit name <b>{self.unit}</b> exactly — '
                                  'a click is not a decision (§12). '
                                  '<a href="/control">back</a></p>')
            act = form.get('action', '')
            if act not in ('start', 'stop', 'restart'):
                return self._deny(403, 'unknown action')
            r = subprocess.run(['systemctl', '--user', act, self.unit],
                               capture_output=True, text=True, timeout=60)
            note = r.stderr.strip() or f'{act}: done'
            return self._page(f'<h1>{self.unit}: {act}</h1><p>{note}</p>'
                              '<p><a href="/control">control</a> · '
                              '<a href="/">fleet</a></p>')
        # /revive
        from panel.create import atomic_write
        tp = self._tombs_path()
        tombs = json.loads(tp.read_text() or '{}') if tp.exists() else {}
        botid = form.get('confirm', '')
        if botid not in tombs:
            return self._page('<h1 class="neg">not revived</h1><p>type the '
                              'botid exactly as the tombstone names it. '
                              '<a href="/control">back</a></p>')
        gone = tombs.pop(botid)
        atomic_write(tp, json.dumps(tombs))
        return self._page(f'<h1>{botid}: tombstone removed</h1>'
                          f'<p class="dim">was: {gone.get("reason")}</p>'
                          '<p>takes effect at the next fleet start (X7) — '
                          'restart from <a href="/control">control</a> when '
                          'ready.</p>')


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(argv):
    if not argv:
        print('usage: python3 -m panel.server <fleet.json> [--hours N]')
        return 2
    Handler.fleet = argv[0]
    if '--hours' in argv:
        Handler.hours = float(argv[argv.index('--hours') + 1])
    port = 0
    if '--port' in argv:
        port = int(argv[argv.index('--port') + 1])
    if '--unit' in argv:
        Handler.unit = argv[argv.index('--unit') + 1]
    if '--token-file' in argv:
        # the persistent-session variant: token survives restarts, stored
        # like a key (0600, refuse looser — the engine's own rule)
        tf = Path(argv[argv.index('--token-file') + 1])
        if tf.exists():
            mode = tf.stat().st_mode & 0o077
            if mode:
                print(f'refusing {tf}: group/other-readable', flush=True)
                return 1
            Handler.token = tf.read_text().strip()
        else:
            Handler.token = secrets.token_urlsafe(16)
            tf.touch(mode=0o600)
            tf.write_text(Handler.token)
    else:
        Handler.token = secrets.token_urlsafe(16)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    Handler.host_ok = f'127.0.0.1:{srv.server_port}'
    print(f'panel: http://{Handler.host_ok}/?t={Handler.token}',
          flush=True)   # journald/pipes: the URL must not sit in a buffer
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
