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
  tombstone across restarts). **X2 PROVEN live 2026-08-20**: the XRP short's
  server-side stop fired and flattened venue-side (JOURNAL 2026-09-25).
  Remaining: a `position_sl` watch adoption.
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

- **MED/LOW burn-down** — the queued list in `docs/archive/AUDIT-2026-08-07.md`:
  sign-only truncation detection, RO match with no re-size, per-venue
  wallet-read isolation, cwd-relative locks/tombstones, probe stranding,
  partially-resting remainder close, M15 deepest-round fallback, grid E9
  cancel-vs-fill blind side, multi-quote TOTAL, backtester bid/ask.
  *(Left via PR #116: half-lot suppression, cumdev refusal, equity
  guard; via PR #117: first-fill truncation tell, RO re-size below 3/4,
  the grid E9 fast-path blind side; via PR #118: per-venue wallet
  isolation — a failed read costs unknown equity, never the cycle —
  and locks/tombstones anchor to the fleet file, not the cwd.)*
  *(Tail closed via PR #119: probe strands named with order id; the
  remainder close places only the uncovered gap and ro_capacity warns
  once; deepest-round restarts hold instead of re-anchoring; per-quote
  totals; the backtest replays against a synthetic 1bp spread.)*
  Remaining, the adoption pair: query-by-clientOrderId resolution
  of ambiguous market writes, and the Nautilus temporal deadband
  on E9 — each needs plumbing (client endpoint; clock injection
  through the stand-down specs): one focused session, not an
  end-of-day patch. Item 2 of the trio (netted sells in the
  coverage walk) was already satisfied by PR #82's deficit
  arithmetic; PR #121 pins it with the feared interleave case.
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

## 6. Found by the 48-day unattended run (JOURNAL 2026-09-25)

Nothing runs until the owner says so; these are what must be true before it does.

- **Dead bots must not report a position.** The snapshot carries a killed
  bot's last belief; the watchdog and the range review read it as live and
  paged a phantom breach every re-alert window for 48 days. The snapshot
  should carry venue truth or nothing for `alive: false`; the watchdog and
  `ops/range_review.py` skip the dead either way.
- **Silent death of the ops layer.** Range review and triage depend on a
  Claude token that expires; when it did, both failed daily with one log
  line and no page. Anything unattended must page on its OWN failure.
- **Log rotation** for the fleet logs (systemd append, one-second cycles).
- **HL counterparty liquidations kill healthy bots** (engine defect, found
  by the post-mortem). `exchange/hyperliquid/truth.py` marks any fill that
  carries HL's `liquidation` object as a venue liquidation of us; HL stamps
  it on both sides of the trade. Fix: compare `liquidatedUser` with the
  account address; a counterparty's liquidation is an ordinary fill. Needs a
  spec with the real fill shape. Both HL grid deaths in the run were this.
- **Backtester short-side inventory** ran ~3× the live bot's cap in the
  replay (T3). Understand before any short-grid replay is believed.
- **Martingale "rounds" in the readout** — 692 fills and zero completed
  rounds counted for the ADA looper; the round latch or the readout's
  round detection needs a look before the 10-round SOAK minimum means
  anything.
- **The slide — wired live, unexercised** (D28; PR B, JOURNAL 2026-09-25
  night: X8 the stop follows the window, G21 confirmation, G22 the persisted
  offset, I3 sized for the widest window, the range review and snapshot
  carry the offset). What remains:
  - **Leverage is a warning, not a rule.** The build warns above 20× on a
    slide row (the 48-day replay at 75× was liquidated on one dip; 10× held).
    A fleet-level leverage rule needs its own D-number from the owner.
  - **Never run live.** Every path is specced against the fake venue; the
    first live slide (demo) is the evidence the soak needs — watch the
    `slide` events, the re-set server stop, and a restart mid-window.
  - Shorts: a short slides down only and never fired in a rally; whether
    shorts belong in a fleet outside a range regime is still the owner's
    question, unchanged by the slide.
- **Snapshot equity is a wallet number.** Seeded demo holdings no bot owns
  moved the curve more than the bots did. Either the snapshot carries the
  readout's D8 split, or the watchdog's equity bounds are known to be
  watching the wrong thing.

## Non-gaps — absent by decision, do not re-invent

Trail/SMA machinery (D10 — range edits do it) · deadband keys (D6 — emergent
from the floor + replenish rule) · martingale range bounds (D13 — depth derives
from the deviation schedule) · martingale floor/cap/damping (D14 — the refused
over-capital series is the cap) · v2's `RECHURN_COOLDOWN` (audit 3.5 —
hysteresis replaced it).
