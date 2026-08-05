#!/bin/sh
# Layer 2b — auto-triage, fired by the fleet's -failed unit after the alert.
# STRICTLY READ-ONLY: it diagnoses and reports; a human approves any fix. The
# guarantee is enforced by ops/triage-settings.json (passed to
# `claude --settings`), not by trust. Degrades instead of failing silently:
# missing CLI or token still produces a Telegram message saying so.
# One triage per fleet per 30 min (stamp file); a triage already running
# absorbs re-triggers (oneshot units ignore triggers while active).
set -u

FLEET="${1:?usage: triage.sh demo|hl}"
REPO=$(cd "$(dirname "$0")/.." && pwd)
LOG="$REPO/logs/triage-$FLEET.log"
STAMP="$REPO/logs/$FLEET-triage.stamp"

case "$FLEET" in
    demo) LABEL="🟠⚫ Bybit"
          DESC="Bybit DEMO fleet — test funds, no real money"
          UNIT=grid-gremlin3-demo
          FLOG=logs/fleet-demo.log
          SNAP=logs/snapshots-demo.jsonl ;;
    hl)   LABEL="🟢🟢 Hyperliquid"
          DESC="Hyperliquid TESTNET fleet — mock USDC only"
          UNIT=grid-gremlin3-hl
          FLOG=logs/fleet-hl-testnet.log
          SNAP=logs/snapshots-hl-testnet.jsonl ;;
    *)    echo "triage.sh: unknown fleet '$FLEET'" >&2; exit 1 ;;
esac

cd "$REPO" || exit 1

# .env is the box's single source of secrets (mode 600). Parse, never source,
# so the file can never execute shell.
while IFS= read -r line; do
    case "$line" in
        ''|\#*) continue ;;
        *=*) export "$line" ;;
    esac
done < "$REPO/.env"

stamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

tg() {
    if [ -n "${TRIAGE_DRY:-}" ]; then
        printf '%s\n' "$1"
        return 0
    fi
    [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || {
        echo "$(stamp) triage: no Telegram credentials in .env" >> "$LOG"
        return 0
    }
    # Telegram's hard cap is 4096 chars; leave headroom.
    curl -s -m 30 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=$(printf '%s' "$1" | cut -c1-3500)" >/dev/null
}

# the rate gate (skipped in dry runs)
if [ -z "${TRIAGE_DRY:-}" ]; then
    now=$(date +%s)
    last=$(cat "$STAMP" 2>/dev/null || echo 0)
    [ $((now - last)) -lt 1800 ] && exit 0
    echo "$now" > "$STAMP"
fi

echo "$(stamp) triage($FLEET): starting" >> "$LOG"

CLAUDE="${CLAUDE_BIN:-$(command -v claude || true)}"
if [ -z "$CLAUDE" ] || [ ! -x "$CLAUDE" ]; then
    tg "$LABEL v3 $FLEET: triage unavailable — claude CLI not found (set CLAUDE_BIN in .env). Fleet is down; please SSH in."
    exit 0
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    tg "$LABEL v3 $FLEET: triage unavailable — CLAUDE_CODE_OAUTH_TOKEN is not set in .env. Fleet is down; please SSH in."
    exit 0
fi

PROMPT="$UNIT.service on this box is failing repeatedly. This is the $DESC —
nothing live is at risk, but the soak is interrupted and the owner wants a cause.

Investigate, READ-ONLY — change nothing, restart nothing, touch no exchange state:
  - journalctl --user -u $UNIT -n 300 --no-pager
  - the tail of $FLOG and $SNAP
  - git log -5 --oneline, and git status
  - classify: code bug / config refusal / venue-API outage / network / host
    (disk, memory, clock). Notes: the build REFUSES the whole fleet on any bad
    row or missing symbol, naming its cause in the log tail; this venue's
    testnet has a history of multi-hour outages (502s) and of changing its
    listed universe across an outage.

Then output ONE plain-text message for the owner, under 3000 characters:
  line 1: the single most likely root cause, in one sentence
  then:   the evidence (quote the key log lines)
  then:   what state the account/orders are believed to be in
  then:   the specific next step you recommend a human take
No markdown, no preamble, no questions. The owner reads it on a phone."

OUT=$(timeout 600 "$CLAUDE" -p "$PROMPT" \
        --settings "$REPO/ops/triage-settings.json" 2>>"$LOG")
RC=$?

if [ $RC -ne 0 ] || [ -z "$OUT" ]; then
    echo "$(stamp) triage($FLEET): claude exited $RC, no usable output" >> "$LOG"
    tg "$LABEL v3 $FLEET: fleet DOWN. Automated triage failed (claude exit $RC) — no diagnosis. Please SSH in: journalctl --user -u $UNIT -n 200"
    exit 0
fi

echo "$(stamp) triage($FLEET): ---" >> "$LOG"
printf '%s\n' "$OUT" >> "$LOG"
tg "$LABEL v3 $FLEET fleet DOWN — triage:

$OUT"
