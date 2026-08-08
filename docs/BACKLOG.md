# Backlog — what v3 does not do yet

The honest ledger, so nothing lives only in a conversation. An item leaves this
file one of two ways: the PR that builds it, or a decision that kills it —
both cited here when they happen. Nothing on this list blocks the current soak.

## 1. Engine — staged by decision (D15, owner may pull any forward)

- **Signal start-conditions** — a round opens on an external signal, not
  immediately. Owner 2026-08-05: flagged for LATER — they do their own TA to
  enter, even with bots.

## 2. Built but not yet exercised live

- **`watch: position_sl` and server-side partial SL** (X2/X3) — X1's
  bot-side fire is PROVEN live (the 2026-08-05 deliberate test, incl. the X7
  tombstone across restarts). Remaining: a server-side SL actually
  triggering venue-side (the revived XRP short now carries one), and a
  `position_sl` watch adoption.
- **Margin-spot SHORT** (D24) — capability-complete and specced; one config
  row away whenever the owner wants it exercised.
- **HL tranches live** (D23/M10) — specced both ways; the HL fleet's margin
  is too committed for a second martingale until the AVAX round closes.
- **HL kline fetch + martingale backtests** — the backtest CLI serves Bybit
  grids only (T3 replays plan_grid); both refusals name themselves.

## 3. Owner-gated — not buildable, only decidable

- **Promotion sign-off** — the path is built cold (D25/F7, PR #45) and
  `docs/PROMOTION.md` is the checklist (evidence gate, key ceremony, cutover
  incl. v2 decommission). What remains is the owner working the checklist
  when the soak's evidence gate is met.

## 4. The panel — where it stands (2026-08-08) and what remains

**Built, specced, live** (PRs #88-#104): the data contract (`report --json`,
one shape for every renderer) · phase View complete (per-bot state, money
columns, bought/sold, range strips, edge distances, stop-now estimate,
watcher health, quiet bots rendered from belief, venue sections, aligned
grid) · rehearse (engine-validated drafts over real candles, hold benchmark,
equity curve) · create/edit/remove for linear grids (four gates: merged-fleet
validation, diff, keyless dry-run, typed confirm; atomic apply, .bak kept) ·
control (start/stop/restart both units + tombstone revival with evidence,
opt-in per launch) · export snapshot · stable tunnel session (pinned port,
0600 token). 320 specs.

*(Keys recipe + red-states quickstart left via PR #106; first-run
init + the on-page key left via PR #109 — README §11.)*

**Remaining, in tackle order:**

1. *(Martingale + spot forms: creation left via PR #107; edits via
   PR #114 — overlays: only carried knobs move, unlisted keys survive.
   Tranches/trailing stay file-only by design.)*
2. **Local-first: DONE for the core** (PR #113 — `--supervise`: control
   spawns/stops the engine as a detached child, pid bookkeeping, F3
   lock stays the only mutex; README quickstart is one terminal, once).
   Remaining under this heading: Windows signal semantics unverified
   (SIGTERM vs terminate()), and a packaging pass (pip/zipapp) if the
   stress-testing group wants installs rather than clones.

## 5. Engine queue (from audit 2026-08-07, unchanged by panel work)

- **MED/LOW burn-down** — the queued list in `docs/AUDIT-2026-08-07.md`:
  sign-only truncation detection, RO match with no re-size, per-venue
  wallet-read isolation, cwd-relative locks/tombstones, probe stranding,
  partially-resting remainder close, M15 deepest-round fallback, grid E9
  cancel-vs-fill blind side, multi-quote TOTAL, backtester bid/ask.
  *(Left via PR #116: half-lot suppression ceil, ≥100% cumdev refusal,
  unknown-equity projection guard.)*
- **Prior-art adoption trio** — deterministic clientOrderIds on
  market/seed writes; netted sells in the G15 coverage walk (passivbot's
  arithmetic, our refusal); Nautilus-style temporal deadband before
  believing venue discrepancies.
- **`ceiling_loose: true`** — designed (DASHBOARD §8), not implemented:
  the coverage check accepts >1.5x cap only with the named switch.
- *(Fee-economics verdict delivered 2026-08-08: over 120h the BTC long
  runs +128.82/trip with fees at 27% of realized, the ETH long
  +8.79/trip at 17% — both clear their fees comfortably; every earlier
  alarm was a truncated-window artifact, the class R9/R7 now guard.)*

## Non-gaps — absent by decision, do not re-invent

Trail/SMA machinery (D10 — range edits do it) · deadband keys (D6 — emergent
from the floor + replenish rule) · martingale range bounds (D13 — depth derives
from the deviation schedule) · martingale floor/cap/damping (D14 — the refused
over-capital series is the cap) · v2's `RECHURN_COOLDOWN` (audit 3.5 —
hysteresis replaced it).
