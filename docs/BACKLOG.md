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

## Non-gaps — absent by decision, do not re-invent

Trail/SMA machinery (D10 — range edits do it) · deadband keys (D6 — emergent
from the floor + replenish rule) · martingale range bounds (D13 — depth derives
from the deviation schedule) · martingale floor/cap/damping (D14 — the refused
over-capital series is the cap) · v2's `RECHURN_COOLDOWN` (audit 3.5 —
hysteresis replaced it).
