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

- **WS wake** — v2 woke on fill events in ~1s; v3 polls on `--interval`. Costs
  nothing at 5s for wide grids; tight grids and martingale safety-order bursts
  would feel it. Needs a decision on whether the added moving part pays.
- **Backtest data fetch** — the backtester (T4-proven against v2) is
  fixture-fed; a kline-fetch convenience would let it run on fresh venue data
  from the CLI.

## 3. Reporting and measurement

- **Per-bot profit readout** — D8 adopted the grid-profit vs total-P&L
  reporting model; the engine journals every fill, but nothing yet *reads* the
  journal back into that shape. This is the tool the current parameter
  experiments (weighted vs uniform rungs, hysteresis on/off, martingale
  multiplier/deviation spreads) are waiting on to be judged.
- **Soak readout doctrine** — define what the A/B fleets must show, and for how
  long, before a parameter question is called. Measure before theorising.

## 4. Ops layer (v2 had these; v3 does not yet)

- **The relay** — inbound Telegram: ask the fleet a question, get a read-only
  answer. v2's relay still runs and serves during the transition.
- **Triage-on-failure** — v2's fourth deploy layer: a read-only headless
  diagnosis attached to the failure alarm, so a page arrives with a cause.
- **Agentic range-review** — routine "is this range still sane" as an ops
  health-check task, not engine code (D10's closing note).
- **Unit templates in-repo** — the systemd units live only on the deploy box;
  genericised templates (placeholder paths — the hygiene rule bars real ones)
  belong under `ops/` so the setup is reproducible from the repo.

## 5. Built but not yet exercised live

- **Spot and inverse** — adapters and specs exist; every soak bot so far is
  linear. A small spot grid in the demo fleet would close this.
- **`watch: position_sl` and server-side partial SL** (X2/X3) — specced and
  shipped; no soak bot has yet fired one live end-to-end.
- **D21 on Hyperliquid, live proof** — the venue-resting martingale exit is in
  the testnet fleet; the round opens when the venue's current testnet outage
  ends. In flight, not done.

## 6. Owner-gated — not buildable, only decidable

- **Promotion criteria** — what the soak must show (duration, finding-rate
  decay, incident-free watchdog record) before v3 touches real funds. Worth
  writing down *before* the soak looks clean.
- **The mainnet path** — deliberately unconstructible today (no flag, HL client
  refuses the env). Building it is itself a gated, spec-pinned slice.
- **v2 decommission** — cutover order for the parked v2 fleet, the relay
  handover, and the key ceremony. A checklist to write with the owner.

## Non-gaps — absent by decision, do not re-invent

Trail/SMA machinery (D10 — range edits do it) · deadband keys (D6 — emergent
from the floor + replenish rule) · martingale range bounds (D13 — depth derives
from the deviation schedule) · martingale floor/cap/damping (D14 — the refused
over-capital series is the cap) · v2's `RECHURN_COOLDOWN` (audit 3.5 —
hysteresis replaced it).
