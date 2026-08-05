# Promotion — how v3 reaches real funds

The path exists (F7/D25) and ships **cold**: both safeties on, no mainnet key
anywhere in this repo's phase. This file is the checklist that turns promotion
into mechanics instead of judgment on the day.

## The double safety (D25)

Mainnet fires only when BOTH are true, per venue:

1. the fleet file declares `"allow_mainnet": true` — committed, reviewed intent;
2. the launch passes `--allow-mainnet` — operator intent, every start.

Either alone refuses, naming the missing half. The demo/testnet env flags are
the helmet; this is the armour. No fleet file in this repo ever carries the
flag (F5) — a mainnet fleet file lives beside the box's `.env`, not in git.

## Gate 1 — evidence (the soak must show)

- [ ] Every grid on the board past its SOAK.md minimum (7 days AND 50 exit
      fills); every martingale past 10 completed rounds.
- [ ] Finding rate flat: no new engine defect for 7 consecutive days —
      alarm-path and venue-outage findings count, config tuning does not.
- [ ] Zero unexplained watchdog breaches over the same window.
- [ ] A stop has fired end-to-end live (X1: flatten, cancel, kill, page) at
      least once, deliberately if the market never obliges.
- [ ] Restart continuity proven across a deploy on BOTH venues (S6, routine by
      now) and across one full box reboot.
- [ ] The readout's owned/unowned split is clean: no unexplained unowned fills
      in the promotion window (F6).

## Gate 2 — the key ceremony

- [ ] New mainnet API keys minted fresh (Bybit: trade-only, no withdrawal, IP-
      pinned to the box; HL: an agent/API wallet key, never the account key).
- [ ] Keys land in the box `.env` only — never the repo, never the workstation.
- [ ] The old v2 mainnet keys revoked at the venue the same hour.
- [ ] First launch is READ-armed only: fleet of one tiny bot, watch one full
      cycle of fills before scaling.

## Gate 3 — cutover order

1. Freeze the promotion-window configs (no experiments mid-cutover).
2. Stop and disable the parked v2 units; archive its logs; tag its final
   commit.
3. Write the mainnet fleet file on the box (smallest viable: one grid, capital
   the owner names, stop mandatory, watchdog mandatory — F1 enforces).
4. Render mainnet units from `ops/systemd/` templates WITH `--allow-mainnet`
   in ExecStart; watchdog timer in a free slot; alert + triage wired.
5. `--allow-mainnet` launch, owner present; verify first ladder against the
   venue UI; watchdog page test (kill the unit once, on purpose).
6. Scale bot by bot, each with its watchdog entry, days apart.

## Standing rules after promotion

- The demo and testnet fleets keep running — they are where changes soak
  first, forever. Nothing deploys to the mainnet unit that has not run a full
  day on demo.
- Every mainnet incident gets a JOURNAL entry before it gets a fix (the v2
  discipline that built this repo).
