# Backlog — what v3 does not do yet

The honest ledger, so nothing lives only in a conversation. An item leaves this
file one of two ways: the PR that builds it, or a decision that kills it —
both cited here when they happen. Nothing on this list blocks the current soak.

## 1. Engine — staged by decision (D15, owner may pull any forward)

- **Partial TPs** — take profit in tranches instead of one whole-position exit.
- **Trailing TP** — let the target follow price once reached.
- **Signal start-conditions** — a round opens on an external signal, not
  immediately (3Commas-style deal-start).
- **Profit reinvest** — fold realised profit back into `capital` instead of
  letting it idle.
- **Cooldown-between-rounds tuning** — `repeat` today restarts a martingale
  round on the next cycle; a configurable pause may belong here.

## 2. Engine — deferred, not yet decided

- **Margin spot** — the owner trades it and wants the capability as an option.
  The vocabulary already validates (`spot_borrow`, `spot_leverage`); no write
  path sends the venue's `isLeverage` flag yet. Direction under discussion
  2026-08-05: model a borrowed short as an "unhedgeable linear perp"
  (negative base balance = short position), longs borrow quote via the
  leverage flag. Decision pass (D24) freezes the semantics before code.

## 3. Built but not yet exercised live

- **`watch: position_sl` and server-side partial SL** (X2/X3) — specced and
  shipped; no soak bot has yet fired one live end-to-end.

## 4. Owner-gated — not buildable, only decidable

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
