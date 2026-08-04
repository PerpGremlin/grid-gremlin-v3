#!/usr/bin/env python3
"""range_review.py — D10's closing note: routine "is this range still sane" as
an ops health-check, NOT engine code. Trail was deleted (D10) because range
edits through the normal diff give trailing when wanted — this is the layer
that notices when such an edit is worth considering, and it NEVER acts.

Shape: a deterministic collector reads each grid's bounds from the fleet
files and the current mark from PUBLIC venue endpoints (stdlib only, no keys,
no gridgremlin import — a broken engine cannot take the review down with it),
then hands the fact sheet to the same read-only Claude cage as triage for a
judgment. No CLI or token → the fact sheet itself is paged. Martingales are
skipped: they have no range (D13).

Run:  python3 ops/range_review.py configs/fleet.demo.json configs/fleet.hl.testnet.json
      RANGE_DRY=1 ...          (print instead of paging)
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETTINGS = REPO / 'ops' / 'triage-settings.json'
TG_LIMIT = 3800
CLAUDE_TIMEOUT = 300
BYBIT_HOST = 'https://api-demo.bybit.com'    # v3's Bybit phase is demo-only
HL_HOST = 'https://api.hyperliquid-testnet.xyz'  # and HL is testnet-only (F5)


def read_env(path):
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = re.split(r'\s+#', v.strip(), maxsplit=1)[0].strip()
    except OSError:
        pass
    return out


def bybit_mark(category, symbol):
    url = (f'{BYBIT_HOST}/v5/market/tickers?'
           + urllib.parse.urlencode({'category': category, 'symbol': symbol}))
    with urllib.request.urlopen(url, timeout=15) as r:
        row = json.load(r)['result']['list'][0]
    return float(row.get('markPrice') or row.get('lastPrice'))


def hl_marks():
    req = urllib.request.Request(HL_HOST + '/info',
                                 data=json.dumps({'type': 'metaAndAssetCtxs'}).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        meta, ctxs = json.load(r)
    return {e['name']: float(c['markPx'])
            for e, c in zip(meta['universe'], ctxs) if c.get('markPx')}


def review_row(cfg, mark):
    """PURE. One grid's facts -> one line."""
    botid = (f"{cfg['market_type'][:3]}{cfg['symbol']}{cfg['side'][0]}"
             .replace('-', ''))
    lo, hi, rungs = cfg['lower'], cfg['upper'], cfg['rungs']
    width = hi - lo
    rung = width / max(rungs - 1, 1)
    if mark is None:
        return f'{botid:<14} {lo:g}..{hi:g}  mark UNKNOWN (venue unreadable)'
    if mark < lo:
        return (f'{botid:<14} {lo:g}..{hi:g}  mark {mark:g}  '
                f'IDLE BELOW range by {(lo - mark) / rung:.1f} rungs')
    if mark > hi:
        return (f'{botid:<14} {lo:g}..{hi:g}  mark {mark:g}  '
                f'IDLE ABOVE range by {(mark - hi) / rung:.1f} rungs')
    pos = (mark - lo) / width
    edge = min(mark - lo, hi - mark)
    return (f'{botid:<14} {lo:g}..{hi:g}  mark {mark:g}  {pos:.0%} up-range, '
            f'{edge / rung:.1f} rungs to the nearer edge')


def collect(fleet_paths):
    lines, skipped = [], 0
    hl = None
    for path in fleet_paths:
        fleet = json.loads(Path(path).read_text())
        for cfg in fleet.get('bots', []):
            if cfg.get('strategy') == 'martingale':
                skipped += 1                      # no range to review (D13)
                continue
            mark = None
            try:
                if cfg.get('venue') == 'hyperliquid':
                    hl = hl_marks() if hl is None else hl
                    mark = hl.get(cfg['symbol'])
                else:
                    mark = bybit_mark(cfg.get('market_type', 'linear'),
                                      cfg['symbol'])
            except Exception:                                    # noqa: BLE001
                pass                              # UNKNOWN is a fact too
            lines.append(review_row(cfg, mark))
    if skipped:
        lines.append(f'({skipped} martingale(s) skipped — no range, D13)')
    return '\n'.join(lines)


def judge(env, facts):
    claude = env.get('CLAUDE_BIN') or shutil.which('claude')
    if not claude or not env.get('CLAUDE_CODE_OAUTH_TOKEN'):
        return None
    prompt = (
        'You are the daily range review for grid-gremlin v3 (test-fund soak, '
        'two fleets). Today\'s facts, computed from live marks:\n---\n'
        f'{facts}\n---\n\n'
        'You may read configs, docs/SOAK.md, and logs for context. Judge each '
        'grid: KEEP (mark comfortably inside), WATCH (near an edge or drifting '
        'one way), or REVIEW BOUNDS (idle outside, or the range no longer fits '
        'how the symbol trades). A grid idling outside its range is by design '
        '(G11) — flag it, do not call it broken. You cannot change anything: '
        'a bounds edit is a workstation task through the normal config diff '
        '(D10) — say what edit you would propose and why. One line per grid, '
        'then at most three sentences overall. Phone-sized, no preamble.')
    try:
        r = subprocess.run([claude, '-p', prompt, '--settings', str(SETTINGS)],
                           capture_output=True, text=True,
                           timeout=CLAUDE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or '').strip()
    return out or None


def page(env, text):
    if not (env.get('TELEGRAM_BOT_TOKEN') and env.get('TELEGRAM_CHAT_ID')):
        print('range-review: no telegram credentials')
        print(text)
        return
    data = urllib.parse.urlencode({'chat_id': env['TELEGRAM_CHAT_ID'],
                                   'text': text[:TG_LIMIT]}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=data)
    urllib.request.urlopen(req, timeout=20).read()


def main(argv):
    import os
    fleets = [a for a in argv if not a.startswith('-')]
    if not fleets:
        print('usage: range_review.py <fleet.json> [...]')
        return 2
    env = read_env(REPO / '.env')
    facts = collect(fleets)
    verdict = judge(env, facts)
    body = verdict if verdict else f'(facts only — no local Claude)\n{facts}'
    text = f'🧌 [vps · range review]\n\n{body}'
    if os.environ.get('RANGE_DRY'):
        print(f'--- facts ---\n{facts}\n--- page ---\n{text}')
        return 0
    page(env, text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
