# ops — the deploy layer, reproducible from the repo

Templates for the systemd `--user` units that run a fleet unattended. The live
box holds the filled-in copies; this directory holds the shape, so the setup
survives the box. Placeholder paths only — the public-repo hygiene rule bars
real ones.

## The four layers (v2's doctrine, carried)

1. `Restart=always` — crashes recover themselves.
2. `OnFailure` → a rate-limited Telegram alert (one page per 30 min max — see
   the stamp-file comment in the template; the naive version paged once per
   retry through a venue outage).
3. The watchdog on a timer — liveness by *output* (snapshot staleness, per-bot
   bounds, equity floor), catching the wedged-but-alive case restarts can't.
   Exit 1 = breached-and-paged = unit success (`SuccessExitStatus=1`); only a
   crash or an undelivered page fails the unit and fires its own alert.
4. Per-fleet timer slots (`*:4/5`, `*:1/5`, …) so ticks never queue behind
   each other on a small box.

## Install

```
# fill the {{PLACEHOLDERS}}, one set per fleet, then:
cp *.service *.timer ~/.config/systemd/user/
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
