#!/usr/bin/env python3
"""relay.py — the INBOUND half of the Telegram channel. Read-only, fail-closed.

v2's relay carried whole (its docstring doctrine still governs; read it there or
in git history). The load-bearing rules, restated:

  * ONE SENDER: TELEGRAM_OWNER_ID or nothing is processed (fail closed).
  * Addressed to us only: a reply to the bot's own message, or a /command —
    enforced here, not trusted to Telegram's privacy mode.
  * PERSIST BEFORE ACK: the inbox row is fsynced before the getUpdates offset
    advances. A crash costs a duplicate; the other order eats a message the
    owner believes he sent. At-least-once is the only acceptable direction.
  * SINGLE CONSUMER: nothing else may poll getUpdates on this token — the
    workstation reads logs/inbox.jsonl over ssh instead. Taking over from the
    v2 relay means seeding logs/relay.state.json with its offset and stopping
    its timer IN THAT ORDER.
  * The Claude it shells to runs under ops/triage-settings.json: it reads
    local state and returns text. It cannot write, restart, or reach the
    network. A request for action is answered with what it would take.

Run:  python3 ops/relay.py            (systemd timer)
      python3 ops/relay.py --once     (one pass, no sends — dry inspection)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INBOX = REPO / 'logs' / 'inbox.jsonl'
STATE = REPO / 'logs' / 'relay.state.json'
SETTINGS = REPO / 'ops' / 'triage-settings.json'
ALIVE = REPO / 'logs' / 'workstation.alive'  # touched by a live workstation session
ALIVE_MAX = 180
TG_LIMIT = 3800
CLAUDE_TIMEOUT = 300


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


def accepted(update, owner_id):
    """PURE. (bool, reason) — owner-only, addressed-to-us-only."""
    msg = update.get('message') or update.get('channel_post') or {}
    if not msg:
        return False, 'no message body'
    if not owner_id:
        return False, 'TELEGRAM_OWNER_ID unset — refusing everything (fail closed)'
    sender = (msg.get('from') or {}).get('id')
    if sender != owner_id:
        return False, f'sender {sender} is not the owner'
    text = (msg.get('text') or '').strip()
    if not text:
        return False, 'no text'
    reply_to = msg.get('reply_to_message') or {}
    if (reply_to.get('from') or {}).get('is_bot'):
        return True, 'reply to the bot'
    if text.startswith('/'):
        return True, 'command'
    return False, 'not a reply to the bot and not a command'


def workstation_live(now=None):
    now = now if now is not None else time.time()
    try:
        age = now - ALIVE.stat().st_mtime
    except OSError:
        return False, None
    return age <= ALIVE_MAX, age


def route(text, ws_live):
    """PURE. ('vc'|'workstation', reason); /vc forces the box to answer."""
    if (text or '').strip().lower().startswith('/vc'):
        return 'vc', 'explicit /vc override'
    if ws_live:
        return 'workstation', 'a workstation session is live — logged for it'
    return 'vc', 'no workstation session'


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def append_inbox(rows):
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(INBOX, 'a') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
        f.flush()
        os.fsync(f.fileno())


def ask_claude(env, text, reply_to_text):
    """Sandboxed claude -p; the settings file is what makes it read-only."""
    claude = env.get('CLAUDE_BIN') or shutil.which('claude')
    if not claude:
        return '(relay: no claude CLI on this box — set CLAUDE_BIN in .env)'
    brief = ''
    brief_path = env.get('RELAY_BRIEF')
    if brief_path:
        try:
            brief = Path(brief_path).read_text()[:6000]
        except OSError:
            pass
    prompt = (
        "You are V.C., the read-only VPS instance of grid-gremlin v3, answering "
        "the owner over Telegram while he is away from his workstation.\n\n"
        "Context: this box soaks TWO v3 fleets on test funds only — the Bybit "
        "DEMO fleet (grid-gremlin3-demo, logs/fleet-demo.log, "
        "logs/snapshots-demo.jsonl) and the Hyperliquid TESTNET fleet "
        "(grid-gremlin3-hl, logs/fleet-hl-testnet.log, "
        "logs/snapshots-hl-testnet.jsonl). docs/SOAK.md is the experiment "
        "registry; docs/JOURNAL.md the build record. The parked v2 checkout "
        "lives beside this repo if history is needed.\n\n"
        + (f"STANDING BRIEF — more current than anything inferable from the "
           f"repo:\n---\n{brief}\n---\n\n" if brief else "")
        + f"He replied to this alert:\n---\n{reply_to_text[:1200]}\n---\n\n"
        f"His message:\n---\n{text[:1200]}\n---\n\n"
        "Answer him. You may read logs, configs, git history and systemd "
        "state. You CANNOT write, deploy, restart, or change any config — "
        "those wait for a workstation session; say so plainly if asked, "
        "including what it would take. Concise, phone-sized: lead with the "
        "answer, then the numbers behind it. No preamble."
    )
    try:
        r = subprocess.run([claude, '-p', prompt, '--settings', str(SETTINGS)],
                           capture_output=True, text=True,
                           timeout=CLAUDE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f'(relay could not reach the local Claude: {e!r})'
    out = (r.stdout or '').strip()
    return out or f'(claude exited {r.returncode} with no output)'


def send(env, text, reply_to_id=None):
    p = {'chat_id': env['TELEGRAM_CHAT_ID'], 'text': text[:TG_LIMIT]}
    if reply_to_id:
        p['reply_to_message_id'] = reply_to_id
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=urllib.parse.urlencode(p).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main(argv):
    dry = '--once' in argv
    env = read_env(REPO / '.env')
    if not env.get('TELEGRAM_BOT_TOKEN') or not env.get('TELEGRAM_CHAT_ID'):
        print('relay: no telegram credentials — nothing to do')
        return 0
    try:
        owner = int(env.get('TELEGRAM_OWNER_ID') or 0)
    except ValueError:
        owner = 0
    if not owner:
        print('relay: TELEGRAM_OWNER_ID unset — refusing to process (fail closed)')
        return 0

    state = load_state()
    offset = state.get('offset', 0)
    url = (f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getUpdates"
           f"?timeout=0&limit=20" + (f"&offset={offset}" if offset else ''))
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            updates = json.load(r).get('result', [])
    except Exception as e:                                       # noqa: BLE001
        print(f'relay: getUpdates failed: {e!r}')
        return 0
    if not updates:
        return 0

    ws_live, ws_age = workstation_live()
    rows, todo = [], []
    for u in updates:
        ok, why = accepted(u, owner)
        msg = u.get('message') or u.get('channel_post') or {}
        who, route_why = route(msg.get('text'), ws_live) if ok else ('-', why)
        rows.append({'t': int(time.time()), 'update_id': u['update_id'],
                     'accepted': ok, 'reason': why,
                     'route': who, 'route_reason': route_why,
                     'ws_alive_age': None if ws_age is None else int(ws_age),
                     'from': (msg.get('from') or {}).get('id'),
                     'message_id': msg.get('message_id'),
                     'text': msg.get('text'),
                     'reply_to': ((msg.get('reply_to_message') or {})
                                  .get('text') or '')[:400]})
        if ok and who == 'vc':
            todo.append((msg, rows[-1]['reply_to']))

    append_inbox(rows)                       # PERSIST BEFORE ACK
    state['offset'] = updates[-1]['update_id'] + 1
    state['last_run'] = int(time.time())
    STATE.write_text(json.dumps(state))

    if ws_live:
        print(f'relay: workstation session live ({int(ws_age)}s) — deferring')
    for msg, ctx in todo:
        print(f"relay: answering {msg.get('message_id')}: "
              f"{(msg.get('text') or '')[:60]!r}")
        if dry:
            continue
        answer = ask_claude(env, msg.get('text') or '', ctx)
        try:
            send(env, f"🧌 [vps · read-only · v3]\n\n{answer}",
                 msg.get('message_id'))
        except Exception as e:                                   # noqa: BLE001
            print(f'relay: send failed: {e!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
