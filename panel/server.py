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
table.fleet{table-layout:fixed;width:100%}td{overflow:hidden;text-overflow:ellipsis}
table{border-collapse:collapse}td,th{padding:.35em .8em;
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
<td><select name="market"><option>linear</option><option>spot</option>
</select></td><td><button>run the gates</button></td></tr></table>
<input type="hidden" name="gg" value="1"></form>
<p class="dim">the stop defaults to mark_price 2% below the lower rung;
edit the file for anything fancier — same contract, other door.</p>

<h1>create a martingale <span class="dim">— the ladder preview does the
compounding; no rehearsal for martingales (§9: the backtester replays
plan_grid only), the gates still judge everything else.</span></h1>
<form method="post" action="/create">
<table><tr><th>symbol</th><th>side</th><th>capital</th><th>lev</th>
<th>base</th><th>safety</th><th>size x</th></tr>
<tr><td><input name="symbol" value="SOLUSDT" size="9"></td>
<td><select name="side"><option>long</option><option>short</option>
</select></td><td><input name="capital" value="5000" size="7"></td>
<td><input name="leverage" value="10" size="3"></td>
<td><input name="base_order_size" value="800" size="6"></td>
<td><input name="safety_order_size" value="800" size="6"></td>
<td><input name="order_size_multiplier" value="1.5" size="4"></td></tr>
<tr><th>dev %</th><th>dev step x</th><th>max SOs</th><th>TP avg %</th>
<th>repeat</th><th>cooldown s</th><th>reinvest</th></tr>
<tr><td><input name="deviation_pct" value="0.008" size="6"></td>
<td><input name="deviation_step_multiplier" value="1.5" size="4"></td>
<td><input name="max_averaging_orders" value="4" size="3"></td>
<td><input name="take_profit_avg_pct" value="0.012" size="6"></td>
<td><input type="checkbox" name="repeat" value="1" checked></td>
<td><input name="repeat_cooldown_seconds" value="600" size="6"></td>
<td><input type="checkbox" name="reinvest" value="1"></td></tr>
<tr><th>ceiling</th><td colspan="5" class="dim">blank = full-depth base
qty x1.2 — the deepest position the schedule can build, plus headroom
</td><td><input name="ceiling" size="8"></td></tr></table>
<input type="hidden" name="gg" value="1">
<input type="hidden" name="strategy" value="martingale">
<button>run the gates</button></form>
<p class="dim">tranches and trailing stay file-only this slice — nested
config deserves a text editor. dev % and TP % are FRACTIONS (0.008 =
0.8%), exactly as the file writes them: one vocabulary, every door.</p>
<p><a href="/">&larr; fleet</a></p>"""


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


def curve_svg(points, width=600, height=80):
    """The rehearsal's equity path as inline SVG — server-side, styleable,
    no scripts, no pan/zoom (§4: that is where the rot lives). The zero
    line is drawn so a curve below it LOOKS below it."""
    if not points or len(points) < 2:
        return ''
    lo, hi = min(points + [0.0]), max(points + [0.0])
    span = (hi - lo) or 1.0
    def y(v):
        return height - (v - lo) / span * (height - 8) - 4
    step = width / (len(points) - 1)
    path = ' '.join(f'{i * step:.1f},{y(v):.1f}'
                    for i, v in enumerate(points))
    return (f'<svg width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
            f'<line x1="0" y1="{y(0.0):.1f}" x2="{width}" '
            f'y2="{y(0.0):.1f}" stroke="var(--line)"/>'
            f'<polyline points="{path}" fill="none" '
            f'stroke="var(--accent)" stroke-width="1.5"/></svg>')


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
    curve = curve_svg(out.get('equity_curve') or [])
    return (f"{FORM}<h1>{draft.get('symbol')} {draft.get('side')} "
            f"{draft.get('lower')}–{draft.get('upper')} x "
            f"{draft.get('rungs')} — {out['bars']} bars</h1>"
            + (f"<p>{curve}</p>" if curve else '')
            + f"<table>{rows}<tr><td>trips / entry fills</td>"
            f"<td>{out['trips']} / {out['entry_fills']}</td></tr>"
            f"<tr><td>ends holding</td><td>{out['held']:.10g}"
            + (f" @ {out['basis']:,.6g}" if out.get('basis') else '')
            + "</td></tr></table>"
            "<p class='dim'>window shown, never annualised. beat the hold "
            "benchmark or hold.</p>")


COLS = ('<colgroup><col style="width:11%"><col style="width:6%">'
        '<col style="width:4%"><col style="width:7%"><col style="width:6%">'
        '<col style="width:11%"><col style="width:7%"><col style="width:7%">'
        '<col style="width:6%"><col style="width:6%"><col style="width:8%">'
        '<col style="width:7%"><col style="width:8%"><col style="width:8%">'
        '<col style="width:6%"></colgroup>')


def section(idx, label, contract):
    age = max(0, int(time.time() - contract['generated_ms'] / 1000))
    rows = []
    belief = ((contract.get('watchdog') or {}).get('belief')
              or {}).get('bots', {})
    for botid, b in contract['bots'].items():
        if b is None:
            # no fills in the window — the engine's own belief fills in,
            # and says so (the snapshot is the bot's belief, not the venue)
            bl = belief.get(botid, {})
            alive = bl.get('alive')
            pos = bl.get('position') or 0.0
            state = ('DEAD' if alive is False else
                     'HOLDING' if abs(pos) > 1e-12 else 'RESTING')
            cls = 'neg' if state == 'DEAD' else 'dim'
            wd0 = contract.get('watchdog') or {}
            ceil0 = (wd0.get('ceilings') or {}).get(botid)
            watch0 = (f'<td class="dim">{abs(pos) / ceil0 * 100:.0f}% of '
                      f'{ceil0:,.4g}</td>' if ceil0
                      else '<td class="neg">UNWATCHED</td>')
            rows.append(
                f'<tr><td>{botid}</td><td class="{cls}">{state}</td>'
                f'<td class="dim">0</td><td class="dim">no fills</td>'
                f'<td class="dim">—</td><td class="dim">'
                + (f'{pos:.10g} (belief)' if abs(pos) > 1e-12 else '—')
                + '</td><td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td><td class="dim">—</td>'
                  '<td class="dim">—</td>'
                + watch0
                + f"<td class='dim'><a href='/edit?fleet={idx}&bot={botid}'>"
                  f"edit</a> <a href='/edit?fleet={idx}&bot={botid}"
                  f"&mode=remove'>remove</a></td></tr>")
            continue
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
            f"{edge}<td>{settle(b, floor)}</td>{watch}"
            f"<td class='dim'><a href='/edit?fleet={idx}&bot={botid}'>edit"
            f"</a> <a href='/edit?fleet={idx}&bot={botid}&mode=remove'>"
            f"remove</a></td></tr>")
    return f"""
<h1>{label} — last {contract['window_hours']:g}h {sweep_note(contract)}
<span class="dim">(read {age}s ago; refreshes every {REFRESH_S}s)</span></h1>
<table class="fleet">{COLS}
<tr><th>bot</th><th>state</th><th>fills</th><th>realized</th>
<th>fees</th><th>open@avg</th><th>unreal</th><th>total</th>
<th>bought</th><th>sold</th><th>range</th><th>edge lo/hi</th>
<th>stop-now est.</th><th>watcher</th><th></th></tr>
{''.join(rows)}</table>
"""


KEY = """<h1>key — what every word on this page means</h1>
<table><tr><th>term</th><th></th></tr>
<tr><td>realized</td><td class="dim">profit from MATCHED buys and sells,
in quote currency (USDT). Money already made or lost; it never moves
again.</td></tr>
<tr><td>fees</td><td class="dim">what the venue charged for every fill
in the window — already excluded from nothing: total = realized − fees
+ unreal.</td></tr>
<tr><td>open@avg</td><td class="dim">what the bot HOLDS right now, at
its average cost. This inventory is not profit and not loss yet.</td></tr>
<tr><td>unreal</td><td class="dim">the open remainder marked to the
current price. Moves every second; becomes real only when sold.</td></tr>
<tr><td>total</td><td class="dim">realized − fees + unreal. The honest
sum — the number other dashboards inflate by leaving parts out.</td></tr>
<tr><td>bought / sold</td><td class="dim">base quantity each way in the
window — how much churn produced the numbers to the left.</td></tr>
<tr><td>range</td><td class="dim">the grid's territory: bar = range,
ticks = rungs, dot = current price.</td></tr>
<tr><td>edge lo/hi</td><td class="dim">distance from price to each end
of the range, as % of price. Small number = near that edge.</td></tr>
<tr><td>stop-now est.</td><td class="dim">roughly what you would receive
if you flattened this bot right now — position at price, minus the
venue fee. An estimate, never a promise.</td></tr>
<tr><td>watcher</td><td class="dim">how much of this bot's watchdog
ceiling its position uses. The watchdog is the independent alarm that
pages if a position outgrows what its config authorises.</td></tr>
<tr><td>HOLDING / FLAT / RESTING</td><td class="dim">holding = has a
position; flat = no position, traded recently; resting = orders working,
nothing held, no fills this window.</td></tr>
<tr><td>DEAD</td><td class="dim">the bot stood down and wrote a
tombstone. Its reason is on the control page; revival is deliberate.
</td></tr>
<tr><td>UNWATCHED</td><td class="dim">no watchdog line for this bot —
the fleet will refuse to build until it has one.</td></tr>
<tr><td>(belief)</td><td class="dim">a number from the engine's own
snapshot rather than venue records — what the bot believes, seconds
old, honest about its source.</td></tr>
<tr><td>* (star)</td><td class="dim">this bot's numbers come from a
window that opened mid-round: partial by construction. Widen the window
for the whole story.</td></tr>
<tr><td>ZERO-SPREAD (R9)</td><td class="dim">exits that closed inside
the fee of their own cost — churn that pays the venue and nobody else.
Should be zero.</td></tr>
<tr><td>trips / per-trip</td><td class="dim">a trip is buy-to-flat (one
completed round trip); per-trip is realized per trip. The grid's
heartbeat.</td></tr>
<tr><td>rounds / SO fills / max depth</td><td class="dim">martingale:
completed rounds; safety orders filled this window; the deepest rung
reached. Depth near max SOs = the schedule nearly exhausted.</td></tr>
<tr><td>hold benchmark</td><td class="dim">what the same capital would
have done just holding over the same window. Beat it or hold.</td></tr>
</table><p><a href="/">&larr; fleet</a></p>"""


def render(labelled, static=None):
    """One renderer, two artefacts (§4): the live page, or — with
    static=timestamp-text — a self-contained export: no refresh, no
    actions, provenance stamped. The numbers can never diverge because
    there is only one code path to diverge from."""
    body = ''.join(section(i, lb, c) for i, (lb, c) in enumerate(labelled))
    notes = ''
    if static:
        chrome = notes + (f'<p class="dim">exported {static} — a snapshot, '
                          'not a live view; the fleet has moved since.</p>')
        head = ''
    else:
        head = f'<meta http-equiv="refresh" content="{REFRESH_S}">'
        chrome = notes + (
            '<p><a href="/rehearse">rehearse a draft grid &rarr;</a> ·'
                  '\n<a href="/create">create a grid &rarr;</a> ·'
                  '\n<a href="/control">control &rarr;</a> ·'
                  '\n<a href="/export">export snapshot &darr;</a> ·'
            '\n<a href="/key">key</a></p>')
    return f"""<!doctype html><meta charset="utf-8">
<title>grid-gremlin</title><style>{CSS}</style>
{head}<button onclick="document.documentElement.classList.toggle('light')">
theme</button>{body}
{chrome}
<p class="dim">this page renders the engine's own readout contract — it
cannot disagree with the terminal. It holds no keys; venue writes are the
engine's alone.</p>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'gg-panel'
    token = ''
    fleets = ()            # venue sections: one per fleet file
    units = ()             # §12: control is opt-in per launch (--units)
    labels = ()
    host_ok = ''
    fleet = ''
    hours = 24.0
    _cache = {}

    def log_message(self, *a):
        pass

    def _contract(self, fleet):
        t, data = Handler._cache.get(fleet, (0.0, None))
        if data is not None and time.time() - t < CACHE_TTL_S:
            return data
        raw = json.loads(Path(fleet).read_text()) if Path(fleet).exists() \
            else {}
        if not raw.get('bots'):
            # a just-initialised world: nothing to report on yet, and the
            # engine's own report would (rightly) refuse an empty fleet
            return {'window_hours': self.hours,
                    'generated_ms': int(time.time() * 1000),
                    'bots': {}, 'unowned': {}}
        out = subprocess.run(
            [sys.executable, '-m', 'gridgremlin.report', fleet,
             '--hours', str(self.hours), '--json'],
            capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout)
        Handler._cache[fleet] = (time.time(), data)
        return data

    def _labelled(self):
        return [(lb, self._contract(f))
                for lb, f in zip(self.labels, self.fleets)]

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
        missing = [f for f in self.fleets if not Path(f).exists()]
        if missing and self.path == '/':
            f0 = missing[0]
            return self._page(
                f'<h1>first run — {f0} does not exist yet</h1>'
                '<p class="dim">init writes a minimal valid fleet + '
                'watchdog pair; then the create flow takes over. The '
                'engine will refuse to start until the first bot exists — '
                'nothing trades unwatched, and nothing trades empty.</p>'
                f'<form method="post" action="/init">'
                f'<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="path" value="{f0}">'
                '<table><tr><th>name (tag)</th><th>equity floor</th>'
                '<th>max margin rate</th></tr><tr>'
                '<td><input name="tag" value="mine" size="10"></td>'
                '<td><input name="equity_min" size="8" '
                'placeholder="e.g. 500"></td>'
                '<td><input name="mm_rate_max" value="0.5" size="5"></td>'
                '</tr></table><button>write the pair</button></form>'
                '<p class="dim">equity floor: the watchdog pages if account '
                'equity falls below this. Margin rate 0.5 = alarm at 50% '
                'of maintenance margin.</p>')
        if self.path == '/key':
            return self._page(KEY)
        if self.path == '/control':
            return self._control_page()
        if self.path == '/export':
            import email.utils
            stamp = email.utils.formatdate(usegmt=True)
            body = render(self._labelled(), static=stamp)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Disposition',
                             'attachment; filename="grid-gremlin-'
                             + time.strftime('%Y%m%d-%H%M%S') + '.html"')
            self.end_headers()
            self.wfile.write(body.encode())
            return
        if self.path.startswith('/edit?'):
            return self._edit_page()
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
        body = (json.dumps({lb: c for lb, c in self._labelled()})
                if self.path == '/data' else render(self._labelled()))
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
        if self.path == '/init':
            from panel.create import init_pair
            try:
                wp = init_pair(form.get('path', ''), form.get('tag', 'mine'),
                               _f(form.get('equity_min')),
                               _f(form.get('mm_rate_max')) or 0.5)
            except Exception as e:                          # noqa: BLE001
                return self._page(f'<h1 class="neg">init refused</h1>'
                                  f'<p class="neg">{e}</p>')
            return self._page(f'<h1>written</h1><p>fleet + watcher pair '
                              f'created ({wp.name} beside it). '
                              '<a href="/create">create your first bot '
                              '&rarr;</a></p>')
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
        fi = int(_f(form.get('fleet')) or 0)
        fleet_p = Path(self.fleets[min(fi, len(self.fleets) - 1)])
        fleet_raw = json.loads(fleet_p.read_text())
        wd_p = Path(fleet_raw['watchdog'])
        wd_raw = json.loads(wd_p.read_text())
        mode = form.get('mode', 'create')
        if apply:
            proposal = json.loads(form.get('proposal', '{}'))
            mode = proposal.get('mode', 'create')
        elif mode == 'remove':
            proposal = {'mode': 'remove', 'orig': form.get('orig', '')}
        elif form.get('strategy') == 'martingale':
            bot = {'strategy': 'martingale', 'market_type': 'linear',
                   'venue': 'bybit',
                   'symbol': form.get('symbol', '').upper(),
                   'side': form.get('side', 'long'),
                   'capital': _f(form.get('capital')),
                   'leverage': _f(form.get('leverage')),
                   'base_order_size': _f(form.get('base_order_size')),
                   'safety_order_size': _f(form.get('safety_order_size')),
                   'order_size_multiplier':
                       _f(form.get('order_size_multiplier')),
                   'deviation_pct': _f(form.get('deviation_pct')),
                   'deviation_step_multiplier':
                       _f(form.get('deviation_step_multiplier')),
                   'max_averaging_orders':
                       int(_f(form.get('max_averaging_orders')) or 0),
                   'take_profit_avg_pct':
                       _f(form.get('take_profit_avg_pct')),
                   'repeat': form.get('repeat') == '1'}
            if _f(form.get('repeat_cooldown_seconds')):
                bot['repeat_cooldown_seconds'] = _f(
                    form.get('repeat_cooldown_seconds'))
            if form.get('reinvest') == '1':
                bot['reinvest'] = True
            proposal = {'mode': mode, 'orig': form.get('orig', ''),
                        'bot': bot,
                        'watchdog': {'max': _f(form.get('ceiling'))}}
        else:
            lo = _f(form.get('lower'))
            bot = {'venue': 'bybit',
                   'symbol': form.get('symbol', '').upper(),
                   'side': form.get('side', 'long'),
                   'capital': _f(form.get('capital')),
                   'lower': lo, 'upper': _f(form.get('upper')),
                   'market_type': (form.get('market') or 'linear'),
                   'rungs': int(_f(form.get('rungs')) or 0),
                   'stop': {'watch': 'mark_price',
                            'level': round((lo or 0) * 0.98, 10)}}
            proposal = {'mode': mode, 'orig': form.get('orig', ''),
                        'bot': bot, 'watchdog':
                        {'max': _f(form.get('ceiling'))}}
        try:
            from panel.create import edit_proposal, remove_proposal
            if mode == 'remove':
                botid, fleet, wd = remove_proposal(fleet_raw, wd_raw,
                                                   proposal['orig'])
                vbot = adapter = None
            else:
                from gridgremlin.config import (validate_grid,
                                                validate_martingale)
                is_mg = proposal['bot'].get('strategy') == 'martingale'
                vbot = (validate_martingale(dict(proposal['bot'])) if is_mg
                        else validate_grid(dict(proposal['bot'])))
                adapter = public_adapter(vbot)               # defaults (A1)
                if proposal['watchdog'].get('max') is None:
                    if is_mg:
                        from panel.create import martingale_preview
                        _, full = martingale_preview(vbot, public_mark(vbot))
                        cap = full
                    else:
                        cap = position_cap(vbot, adapter,
                                           grid_rungs(vbot, adapter))
                    proposal['watchdog']['max'] = round(
                        cap * CEILING_PREFILL, 6)
                if mode == 'edit':
                    botid, fleet, wd = edit_proposal(
                        fleet_raw, wd_raw, proposal['orig'],
                        proposal['bot'], proposal['watchdog']['max'])
                else:
                    botid, fleet, wd = merge_proposal(fleet_raw, wd_raw,
                                                      proposal)
            refusal = validate_whole(fleet, wd, lambda cfg: adapter
                                     if adapter is not None
                                     and cfg is proposal.get('bot')
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
        if mode == 'remove':
            ladder_html = '<p class="dim">removal: no ladder to dry-run — '\
                          'the diff is the whole change.</p>'
        elif proposal['bot'].get('strategy') == 'martingale':
            from panel.create import martingale_preview
            mark = public_mark(vbot)
            rows_, full = martingale_preview(vbot, mark)
            lrows = ''.join(
                f"<tr><td>{'base' if r['rung'] == 0 else 'SO ' + str(r['rung'])}"
                f"</td><td>{r['price']:,.6g}</td>"
                f"<td>{r['notional']:,.6g}</td><td>{r['qty']:,.6g}</td>"
                f"<td>{r['cum_notional']:,.6g}</td>"
                f"<td>{r['cum_qty']:,.6g}</td></tr>" for r in rows_)
            ladder_html = (
                f'<h1 class="dim">the deviation ladder anchored at mark '
                f'{mark:,.6g} — prices move with the anchor; sizes and '
                f'depth do not</h1><table><tr><th>rung</th><th>price</th>'
                f'<th>notional</th><th>qty</th><th>cum notional</th>'
                f'<th>cum qty</th></tr>{lrows}</table>'
                f'<p class="dim">full depth: {full:,.6g} base — the '
                f'ceiling watches this number.</p>')
        else:
            mark = public_mark(vbot)
            ladder = dry_ladder(vbot, adapter, mark)
            lrows = ''.join(
                f"<tr><td>{o['side']}</td><td>{o['price']:,.6g}</td>"
                f"<td>{o['qty']:,.6g}</td></tr>" for o in ladder)
            ladder_html = (f'<h1 class="dim">the ladder at mark '
                           f'{mark:,.6g} (dry-run — nothing placed)</h1>'
                           f'<table><tr><th>side</th><th>price</th>'
                           f'<th>qty</th></tr>{lrows}</table>')
        diffs = (unified_diff(fleet_p.read_text(), new_fleet, fleet_p.name)
                 + unified_diff(wd_p.read_text(), new_wd, wd_p.name))
        pj = json.dumps(proposal).replace('"', '&quot;')
        return self._page(
            f'<h1>{botid} — {mode}: gates passed</h1>'
            f'<h1 class="dim">the diff</h1><pre class="dim">{diffs}</pre>'
            + ladder_html +
            f'<form method="post" action="/apply">'
            f'<input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="proposal" value="{pj}">'
            f'type the botid to write the files: '
            f'<input name="confirm" size="16" placeholder="{botid}">'
            f'<button>apply</button></form>'
            f'<p class="dim">apply writes files only; the running fleet is '
            f'untouched until restarted (§11).</p>')


    def _tombs_path(self):
        return Path(self.fleets[0]).parent.parent / 'logs' / 'tombstones.json'

    def _edit_page(self):
        q = dict(urllib.parse.parse_qsl(self.path.split('?', 1)[1]))
        fi = int(q.get('fleet') or 0)
        botid = q.get('bot', '')
        fleet_raw = json.loads(Path(self.fleets[fi]).read_text())
        from gridgremlin.apply import make_botid as _mb
        bot = next((b for b in fleet_raw.get('bots', [])
                    if _mb(b['market_type'], b['symbol'], b['side'])
                    == botid), None)
        if bot is None:
            return self._deny(404, f'{botid}: not in this fleet')
        if q.get('mode') == 'remove':
            return self._page(
                f'<h1>remove {botid}</h1><p class="dim">the bot and its '
                'watchdog line leave together; the remaining fleet must '
                'still validate (F1). The running fleet is untouched until '
                'restarted (§11).</p>'
                f'<form method="post" action="/create">'
                f'<input type="hidden" name="gg" value="1">'
                f'<input type="hidden" name="mode" value="remove">'
                f'<input type="hidden" name="fleet" value="{fi}">'
                f'<input type="hidden" name="orig" value="{botid}">'
                f'<button>run the gates</button></form>'
                f'<p><a href="/">&larr; fleet</a></p>')
        if bot.get('strategy', 'grid') != 'grid' \
                or bot.get('market_type') != 'linear':
            return self._page(f'<h1 class="dim">{botid}</h1><p>this slice '
                              'edits linear grids only — the file door '
                              'covers the rest (same contract, §8).</p>')
        w = json.loads(Path(json.loads(Path(self.fleets[fi]).read_text())
                            ['watchdog']).read_text())
        wmax = (w.get('positions', {}).get(botid) or {}).get('max', '')
        return self._page(
            f'<h1>edit {botid} <span class="dim">— identity is fixed; '
            'range, rungs, capital, ceiling move (§11)</span></h1>'
            f'<form method="post" action="/create">'
            f'<table><tr><th>lower</th><th>upper</th><th>rungs</th>'
            f'<th>capital</th><th>ceiling</th><th></th></tr><tr>'
            f'<td><input name="lower" value="{bot.get("lower")}" size="8">'
            f'</td><td><input name="upper" value="{bot.get("upper")}" '
            f'size="8"></td><td><input name="rungs" '
            f'value="{bot.get("rungs")}" size="4"></td>'
            f'<td><input name="capital" value="{bot.get("capital")}" '
            f'size="7"></td><td><input name="ceiling" value="{wmax}" '
            f'size="8"></td><td><button>run the gates</button></td></tr>'
            f'</table><input type="hidden" name="gg" value="1">'
            f'<input type="hidden" name="mode" value="edit">'
            f'<input type="hidden" name="fleet" value="{fi}">'
            f'<input type="hidden" name="orig" value="{botid}">'
            f'<input type="hidden" name="symbol" value="{bot["symbol"]}">'
            f'<input type="hidden" name="side" value="{bot["side"]}">'
            f'</form><p><a href="/">&larr; fleet</a></p>')

    def _control_page(self):
        if not self.units:
            return self._deny(404, 'control is not armed on this panel '
                                   '(start it with --units) — §12')
        rows = []
        for u in self.units:
            state = subprocess.run(['systemctl', '--user', 'is-active', u],
                                   capture_output=True, text=True
                                   ).stdout.strip()
            cls = 'pos' if state == 'active' else 'neg'
            rows.append(f'<p>unit <b>{u}</b>: <span class="{cls}">{state}'
                        '</span></p>')
        units_html = ''.join(rows)
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
{units_html}
<form method="post" action="/unit">
<input type="hidden" name="gg" value="1">
<select name="action"><option>restart</option><option>stop</option>
<option>start</option></select>
type a unit name to confirm: <input name="confirm" size="22">
<button>do it</button></form>
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
        if not self.units:
            return self._deny(404, 'control is not armed on this panel')
        if path == '/unit':
            unit = form.get('confirm', '')
            if unit not in self.units:
                return self._page('<h1 class="neg">not done</h1><p>type one '
                                  'of the armed unit names exactly — a '
                                  'click is not a decision (§12). '
                                  '<a href="/control">back</a></p>')
            act = form.get('action', '')
            if act not in ('start', 'stop', 'restart'):
                return self._deny(403, 'unknown action')
            r = subprocess.run(['systemctl', '--user', act, unit],
                               capture_output=True, text=True, timeout=60)
            note = r.stderr.strip() or f'{act}: done'
            return self._page(f'<h1>{unit}: {act}</h1><p>{note}</p>'
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
    if '--hours' in argv:
        i = argv.index('--hours')
        Handler.hours = float(argv[i + 1])
        del argv[i:i + 2]
    if '--units' in argv:
        i = argv.index('--units')
        Handler.units = tuple(argv[i + 1].split(','))
        del argv[i:i + 2]
    port = 0
    if '--port' in argv:
        port = int(argv[argv.index('--port') + 1])
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
    Handler.fleets = tuple(a for a in argv if a.endswith('.json'))
    def _label(f):
        stem = Path(f).stem.replace('fleet.', '')
        try:
            bots = json.loads(Path(f).read_text()).get('bots') or []
            venue = bots[0].get('venue', 'bybit') if bots else None
        except (OSError, ValueError):
            venue = None
        if not venue:
            return stem
        # venue first, plus the stem's final token — the environment word
        # (demo, testnet, mine); abbreviations like 'hl' never survive
        return f"{venue} {stem.split('.')[-1]}"
    Handler.labels = tuple(_label(f) for f in Handler.fleets)
    if not Handler.fleets:
        print('usage: python3 -m panel.server <fleet.json>... '
              '[--hours N] [--port P] [--token-file F] [--units a,b]')
        return 2
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
