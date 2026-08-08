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
<p><a href="/rehearse">rehearse a draft grid &rarr;</a></p>
<p class="dim">stop-now est. = position at mark less the venue fee floor —
an estimate, not a promise; the venue settles what it settles.<br>
* window opened mid-round: partial numbers (R7).
This page renders the engine's own readout contract — it cannot disagree
with the terminal. It holds no keys and can write nothing.</p>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'gg-panel'
    token = ''
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
        if self.path != '/rehearse':
            return self._deny(404, 'no such action')
        raw = self.rfile.read(min(int(self.headers.get(
            'Content-Length') or 0), 4096)).decode()
        form = dict(urllib.parse.parse_qsl(raw))
        if form.pop('gg', None) != '1':
            return self._deny(403, 'missing form token')
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
    Handler.token = secrets.token_urlsafe(16)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Handler.host_ok = f'127.0.0.1:{srv.server_port}'
    print(f'panel: http://{Handler.host_ok}/?t={Handler.token}',
          flush=True)   # journald/pipes: the URL must not sit in a buffer
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
