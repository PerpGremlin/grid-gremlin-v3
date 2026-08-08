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

*(Keys recipe and the red-states quickstart left via PR #106 —
README §11.)*

**Remaining, in tackle order:**

1. **Martingale + spot EDIT forms** — creation left via PR #107 (form,
   deviation-ladder preview, ceiling from full depth, spot grids in the
   create form; tranches/trailing stay file-only). Edit for
   martingale/spot rows remains grids-only.
2. **First-run `init`** — the panel can only merge into an existing
   fleet+watchdog pair; a no-agent user hits a cliff at clone. A guided
   flow (or CLI) writing a minimal valid pair from a template, refusals
   guiding each field. Cheap, unblocks strangers.
3. **Local-first packaging** — the real project: engine + panel on a
   stranger's PC, no VPS, no tunnel, one command to a bookmark. Promoted
   by the no-agent question (2026-08-08); everything built transfers, the
   plumbing around it changes. Design §4's centre case, finally built.

## 5. Engine queue (from audit 2026-08-07, unchanged by panel work)

- **MED/LOW burn-down** — the queued list in `docs/AUDIT-2026-08-07.md`:
  sign-only truncation detection, RO match with no re-size, per-venue
  wallet-read isolation, cwd-relative locks/tombstones, probe stranding,
  partially-resting remainder close, M15 deepest-round fallback, grid E9
  cancel-vs-fill blind side, multi-quote TOTAL, ≥100% cumdev refusal,
  backtester bid/ask.
- **Prior-art adoption trio** — deterministic clientOrderIds on
  market/seed writes; netted sells in the G15 coverage walk (passivbot's
  arithmetic, our refusal); Nautilus-style temporal deadband before
  believing venue discrepancies.
- **`ceiling_loose: true`** — designed (DASHBOARD §8), not implemented:
  the coverage check accepts >1.5x cap only with the named switch.
- **Fee-economics verdict** — the wide-window readout on the demo BTC and
  ETH longs (flagged 2026-08-07): is the ETH long genuinely trading
  inside its fees? An evening's readout, not code.

## Non-gaps — absent by decision, do not re-invent

Trail/SMA machinery (D10 — range edits do it) · deadband keys (D6 — emergent
from the floor + replenish rule) · martingale range bounds (D13 — depth derives
from the deviation schedule) · martingale floor/cap/damping (D14 — the refused
over-capital series is the cap) · v2's `RECHURN_COOLDOWN` (audit 3.5 —
hysteresis replaced it).
