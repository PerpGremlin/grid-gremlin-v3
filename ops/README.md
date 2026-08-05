# ops — the deploy layer, reproducible from the repo

Templates for the systemd `--user` units that run a fleet unattended. The live
box holds the filled-in copies; this directory holds the shape, so the setup
survives the box. Placeholder paths only — the public-repo hygiene rule bars
real ones.

## The layers (v2's four, carried, plus two)

1. `Restart=always` — crashes recover themselves.
2. `OnFailure` → a rate-limited Telegram alert (one page per 30 min max — see
   the stamp-file comment in the template; the naive version paged once per
   retry through a venue outage), then **read-only Claude triage**
   (`ops/triage.sh <fleet>`): a headless diagnosis paged after the alert, so
   the page arrives with a cause. Read-only is enforced by
   `ops/triage-settings.json` passed to `claude --settings` — not by trust.
   Needs `CLAUDE_CODE_OAUTH_TOKEN` (and optionally `CLAUDE_BIN`) in `.env`;
   missing either degrades to a "triage unavailable" page, never silence.
   Test with `TRIAGE_DRY=1 ops/triage.sh demo` (prints instead of paging).
3. The watchdog on a timer — liveness by *output* (snapshot staleness, per-bot
   bounds, equity floor), catching the wedged-but-alive case restarts can't.
   Exit 1 = breached-and-paged = unit success (`SuccessExitStatus=1`); only a
   crash or an undelivered page fails the unit and fires its own alert.
4. Per-fleet timer slots (`*:4/5`, `*:1/5`, …) so ticks never queue behind
   each other on a small box.
5. **The range review** (`ops/range_review.py`, daily timer) — D10's closing
   note: a read-only "are the bounds still sane" page. A stdlib-only
   collector computes each grid's mark-vs-bounds facts from public
   endpoints; the triage cage judges KEEP / WATCH / REVIEW BOUNDS; no
   Claude → the fact sheet pages as-is. It never acts — a bounds edit is a
   workstation task through the normal config diff. Test:
   `RANGE_DRY=1 python3 ops/range_review.py configs/fleet.demo.json ...`
6. **The relay** (`ops/relay.py`, every-minute timer) — the inbound half:
   the owner replies to a bot message (or sends a /command) on Telegram and
   gets a read-only answer from the box, in the same settings cage as
   triage. Owner-only (`TELEGRAM_OWNER_ID`, fail closed), persist-before-ack
   inbox at `logs/inbox.jsonl`, single getUpdates consumer per bot token —
   never run two relays on one token. `/vc` forces the box to answer even
   when a workstation session is live. Deliberately no OnFailure alarm.

## Install

```
# fill the {{PLACEHOLDERS}} in ops/systemd/*.template, one set per fleet,
# save each WITHOUT the .template suffix, then:
cp grid-gremlin3-*.service grid-gremlin3-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now grid-gremlin3-<fleet>.service
systemctl --user enable --now grid-gremlin3-<fleet>-watchdog.timer
loginctl enable-linger $USER        # units survive logout
```

| placeholder | meaning |
|---|---|
| `{{FLEET}}` | short fleet tag (`demo`, `hl`, …) — names units, logs, stamps |
| `{{DESC}}` | one-line description shown by systemctl |
| `{{REPO_DIR}}` | absolute path of the deployed checkout |
| `{{FLEET_CONFIG}}` / `{{WATCHDOG_CONFIG}}` | file names under `configs/` |
| `{{START_LIMIT_INTERVAL}}` | `600` normally; `0` for patient-retry fleets (venue outages) |
| `{{RESTART_SEC}}` | `10` normally; longer (`30`) for patient-retry fleets |
| `{{SLOT}}` | the fleet's own watchdog minute slot, e.g. `*:4/5` |

The fleet needs `{{REPO_DIR}}/.env` (chmod 600) with the venue keys and
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`; nothing here works without a
watchdog config covering every bot (F1) — the fleet refuses to build without
one.
