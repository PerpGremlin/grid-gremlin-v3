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
        rows.append(
            f'<tr><td>{botid}{note}</td><td class="dim">{state}</td>'
            f"<td>{b['fills']}</td>{money(b['realized'])}"
            f"{money(b['fees'], cls=False)}<td>{openat}</td>"
            f"{money(b['unreal_at_mark'])}{money(total)}"
            f"<td>{b['bought']:,.4g}</td><td>{b['sold']:,.4g}</td></tr>")
    return f"""<!doctype html><meta charset="utf-8">
<title>grid-gremlin</title><style>{CSS}</style>
<meta http-equiv="refresh" content="{REFRESH_S}">
<button onclick="document.documentElement.classList.toggle('light')">
theme</button>
<h1>grid-gremlin — last {contract['window_hours']:g}h
<span class="dim">(read {age}s ago; refreshes every {REFRESH_S}s)</span></h1>
<table><tr><th>bot</th><th>state</th><th>fills</th><th>realized</th>
<th>fees</th><th>open@avg</th><th>unreal</th><th>total</th>
<th>bought</th><th>sold</th></tr>{''.join(rows)}</table>
<p class="dim">* window opened mid-round: partial numbers (R7).
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
        body = (json.dumps(self._contract()) if self.path == '/data'
                else render(self._contract()))
        self.send_response(200)
        self.send_header('Content-Type',
                         'application/json' if self.path == '/data'
                         else 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body.encode())


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
