# SPEC — the invariants

**Status: decided, 2026-08-04 — every former ⚠ DECIDE is resolved; the record of who
decided what is `DECISIONS.md` (D-numbers cited inline). Numbering is stable** — cite
IDs in reviews, commits, and conversation. Each line is one statement that is true or
false, with its source (an incident, a decision, or a study — see `research/`). The linkage
to the suite is the NAME: each spec function carries the ID it pins
(`spec_G7_...`), greppable in both directions.

Rules of this file: one sentence per invariant · unit named where one exists · nothing
enters the code that isn't stated here first · nothing is stated here that a spec can't
eventually pin (T1).

---

## E — the engine core

- **E1** `plan(config, truth)` is pure: no I/O, no clock, no randomness, no module state.
  *(DESIGN §0; what makes backtest parity and every golden test possible)*
- **E2** `apply()` is the only writer; cancels run before creates.
- **E3** The exchange is the only durable state: every in-memory quantity is either
  derivable from venue + config or explicitly documented as reset-on-restart. *(OPERATING
  idea 1; the restart-resets list in v2-history §2)*
- **E4** `plan()` is lookahead-free: the same truth prefix produces the same orders
  regardless of what data follows. *(freqtrade study — "the single highest-value steal")*
- **E5** A partial truth read is an error, never a result — refuse and retry, don't
  truncate. *(the order-runaway incident, 2026-07-30)*
- **E6** The engine reacts to error *kinds*, never venue codes; `ambiguous` means "the
  write may have landed" and defers to the next truth read.
- **E7** No error kind kills: every kind maps to retry, backoff, skip, or warn;
  stand-down happens only by stop rule or operator. This holds at the fleet loop
  too: a failed read or venue error costs the cycle, never the process — no
  snapshot is written for a lost cycle, so a persistent outage still raises the
  watchdog's staleness page. *(two overnight TLS resets killed the HL unit,
  2026-08-05)*
- **E8** Unknown is not flat: a failed startup read refuses to trade. *(nautilus TAKE)*

## A — contract maths (the adapter seam)

- **A1** Everything instrument-shaped is asked from the exchange at startup, never
  declared in config.
- **A2** Quantity rounding always floors — never place more than intended; price rounds
  to tick.
- **A3** One `placeable(qty, price)` predicate at plan time folds min-qty, qty-step,
  min-notional, and affordability; an unplaceable order is never intent. *(hummingbot
  counter-example)*
- **A4** Units never mix: inverse PnL is base-coin, never summed with quote PnL.
  *(v1's +$396k bug)*
- **A5** `position_idx` derives jointly from (side, reduce_only).
- **A6** The adapter seam exists from day one even with one venue; a second venue is a
  slice, not a fork.

## G — the grid

- **G1** The lattice is computed once from `{lower, upper, rungs}`, tick-rounded; price
  never moves it. *(v1's central bug; §5d)*
- **G2** Exactly one of {count, spacing} is given, the other derives, and the stored pair
  is reconciled — the config never carries a spacing the lattice doesn't have. *(config
  study M9)*
- **G3** N rungs span N−1 gaps; the divisor is load-bearing. *(GRID-MATHS §1)*
- **G4** The lot is the one canonical inventory unit, priced at the split ref in every
  position state; exit ladder, cap headroom, and entry suppression all count in it.
  *(D5; CONCEPTS §12·N2)*
- **G5** Entries rest only on the entry side of the split ref; exits only beyond the
  basis-protected floor.
- **G6** The exit floor is `max(ref, basis × (1 + fee_floor))` — the grid never sells
  below cost plus fees; the fee floor is a constant, not a knob.
- **G7** An entry rung never re-arms while its lot is unexited — observable from arming
  order, entry side only. *(the owner's invariant; the stacking incident, 2026-08-02)*
- **G8** The exit ladder covers the sellable position one lot per rung, nearest-first;
  remainders fold without creating sub-lot rungs; the nearest exit sits within ~one rung
  of the mark. *(the dead-band incident, 2026-07-31)*
- **G9** The floor (`min_position`) core is never offered for sale; the cap measures
  *held* while the ladder covers *held − floor* — two named quantities, never one
  variable. *(the overnight cap failure)*
- **G10** Entry headroom is whole lots under the cap; zero headroom stops entries and
  nothing else.
- **G11** Out of range the grid idles — it never chases; it ends only when its stop
  fires or the position is closed from outside (S7). *(§5d; field consensus; D1)*
- **G12** The engine is netted (Camp B): the ladder re-derives from the net position;
  no per-rung paired state exists anywhere. *(decided 2026-07-20; ALIGNMENT §1)*
- **G13** No planned order is ever marketable — in any position state, including every
  adoption case: entries only below the ref, exits only above their floor, the cross
  guard drops anything near the opposite quote, and post-only is the venue-enforced
  backstop (a crossing order is rejected, never filled). Pinned by sabotage: with the
  split or the floor removed, the guard and the venue must still refuse. *(the owner's
  adoption concern, 2026-08-04; D6)*

## W — the window

- **W1** The window limits placement, never cancellation.
- **W2** One named window anchor, used by every consumer — no raw-vs-sticky split
  between the window and the planner. *(audit 3.4; CONCEPTS §12·N4)*
- **W3** A resting, still-planned order outside the window is left alone.

## B — bands and churn guards

- **B1** One mechanism per boundary, one name each; "deadband" and "hysteresis" appear
  unqualified nowhere. The only banded mechanism is the split hysteresis (B2): the
  no-trade behaviour is emergent (B9) and trail is retired (D10). *(ALIGNMENT §13.6; D6,
  D10)*
- **B2** Split hysteresis: the split ref moves only when price has moved more than the
  band (a fraction of the *narrowest* rung gap), and then snaps to current.
- **B3** The cross guard — nothing rests within `max(spread, guard-bps of mid)` of the
  opposite quote — has exactly one implementation, shared by planner and placer.
  *(CONCEPTS §12·N6)*
- **B4** A rung whose exit already rests is exempt from the cross-guard drop; resting
  detection keys on side, never on reduce_only. *(the spot-exit bug)*
- **B5** A rung repeatedly placed-but-not-resting cools off; a rung whose position moved
  is trading, not flapping, and is never cooled. *(the actively-trading-rung bug)*
- **B6** Every cooldown is per-cause: distinguishable in state, in logs, and in events.
  *(CONCEPTS §12·N9)*
- **B7** Margin backoff halts growth only — cancels still run — doubling to a ceiling,
  retrying forever.
- **B8** Spacing must clear the guard band with stated margin, checked at config time
  against the true minimum gap, not the mean. *(the gold-grid measurement; strategy
  study D11)*
- **B9** There is no configurable no-trade band: the dissolving suppression around an
  adopted basis emerges from G7 + G9 + G6 — entries release furthest-from-mark first as
  exits fill, converging on the basis. v2's `no_trade_pct` family and the ratchet are
  retired. *(D6, the owner's dissolution description)*

## M — the martingale

- **M1** The martingale is the grid's ladder math run with different data: one
  direction, cumulative-prefix suppression, no per-rung exits — one implementation,
  zero duplicated formulas. *(audit 3.2/3.3)*
- **M2** The config speaks 3Commas' vocabulary — `base_order`, `safety_order`,
  order-size multiplier (of the previous order), `deviation`,
  `deviation_step_multiplier`, `max_averaging_orders` — and the validator expands the
  full series, refusing any ladder whose total exceeds `capital`, stating the number in
  the error. *(D11)*
- **M3** A round is never without an exit: the whole-position TP is set before the
  round rests, and a target the market has run through closes at the target or better
  via reduce-only marketable limit. *(the stale-target incident)*
- **M4** The round TP measures from average entry, recomputed as fills deepen, the
  basis named into the key. *(D12)*
- **M5** `repeat` re-anchors only from flat; an absolute TP is refused alongside it.
- **M5a** On a venue that hosts the position-TP, a TP fill and an operator's manual
  close are INDISTINGUISHABLE in truth (both leave flat with no owned order gone) —
  a repeat martingale there re-enters after a manual close; the watchdog's
  `assumes_sole_actor` is the assumption that makes this safe, and on the resting-
  exit venue S7 detects it properly. *(audit M1 — documented limitation)*
- **M6** Round state is venue-derivable: a restart adopts the resting TP and never
  rewrites a live round's exit. *(the restart-flattens-a-round incident)*
- **M7** The martingale carries no floor/cap/damping keys: its cap is the
  refused-if-over-capital series, a floor is meaningless under a whole-position TP, and
  damping guards a boundary it doesn't have — absence is derived, not missing. *(D14)*
- **M8** The martingale has no range bounds: ladder depth derives from the deviation
  schedule × `max_averaging_orders`, and the risk is stated as the required-capital
  number at load. The grid keeps its bounds. *(D13)*
- **M9** Staged beyond the skeleton, not in it: signal start conditions (owner-
  deferred — they do their own TA). *(D15; partials/trailing left via D23 → M10/M11;
  reinvest and the cooldown left via D26 → M12/M13)*
- **M10** A round's exit may be TRANCHED (D23): shares of one position at ascending
  targets, summing to one, every price re-anchored from the average as fills deepen —
  venue-hosted partial TPs where the venue hosts them, several D21 resting exits
  where it does not. A tranche the mark has PASSED is done — never re-placed below
  mark (the venue refuses those, correctly); the remaining shares renormalise over
  what is still held, and with every target met the remainder closes marketable at
  the deepest target, or better. The same law as M3, split into shares. *(the ADA
  re-anchor warns, 2026-08-05)*
- **M11** Trailing rides the venue or does not exist: set once per round from the
  average, the venue moves it from there; refused where the venue cannot host it.
  *(D23)*
- **M12** Reinvest is a toggle (D26): on, the round's sizes scale by
  1 + realized-net/capital over the last 30 days of the bot's own venue fills
  (bounded — an epoch-0 history pull was ~3,000 requests, the audit's H1; the
  window is stated in the event), restart-proof by derivation — floored at 0 (losses shrink, never grow) and CAPPED at
  1.2, the watchdog ceiling's own headroom (F2); beyond +20% the owner raises
  `capital` in config, ceiling reviewed together. Grids reinvest only by that
  manual path; the key refuses on a grid, naming it.
- **M13** The round cooldown anchors to the VENUE's timestamp of the TP fill, never
  a process clock — `repeat_cooldown_seconds` after the last owned fill; a restart
  re-derives it; refused without `repeat`. *(D26 — "so martingale bots dont just
  spam an entry immediately after an exit")*

## S — start states

- **S1** From flat, every basis-anchored mechanism is inert by construction — verified
  by identity, not by tolerance.
- **S2** Seeding is observable as already-done from the venue alone; a restart never
  re-seeds.
- **S3** Seeding is a config toggle for flat starts: a market buy covering the
  exit-side rungs implied by bounds + mark (lower in range ⇒ larger seed); on failure,
  refuse and retry with backoff; windowing governs which exits rest, never how much is
  seeded. *(D9)*
- **S4** Adopting: the venue's basis always wins; a basis is never invented, fills are
  never fabricated, and a position the bot cannot explain halts and alerts. *(nautilus
  REJECT of phantom orders)*
- **S5** An adopted basis beyond the range means no exits, one warning, and the position
  left to the operator.
- **S6** A restart re-adopts resting orders by identity with zero churn; every quantity
  that does reset on restart is on a named list with its consequence stated.
- **S7** Involuntary flat is terminal: a position that reaches zero through anything
  other than our own exits (a stop, a manual close — distinguishable by order
  ownership) ends the bot — cancel owned orders, kill, page, never restart. *(D1)*
- **S8** Every non-collapsing cell of the start matrix (state × mark position × basis
  state × position size × venue-basis × foreign orders) has a numbered spec row in this
  section's appendix.

## I — identity and orders

- **I1** Every order carries `{botid}-{rung}-{gen}`; ownership is the prefix plus a
  parsing rung; foreign orders are never cancelled, amended, or counted.
- **I2** One bot owns one `(category, symbol, positionIdx)`; the fleet refuses
  collisions at build.
- **I3** The id fits every venue's link limit, checked at build with a refusal — never a
  silent row skip.
- **I4** Fills deduplicate by venue execution id, across reconnects and restarts.
- **I5** Market-path orders (seed, martingale base, stop-flatten) carry an owned link
  like every other order — I1 has no exceptions; an unattributable own-fill is a
  defect. *(found by R3's unowned bucket, first live readout)*

## V — venue and truth

- **V1** The truth contract is a schema, not a convention: one validated shape, same
  keys, both venues, pinned by a shared spec.
- **V2** Every truth field carries its unit; per-venue period differences (funding) are
  normalised at read time, never left to the consumer. *(CONCEPTS §12·N10)*
- **V3** Truth reads are pure reads: no read mutates cache state that another read
  depends on. *(the HL cache coupling)*
- **V4** A method that exists on two venues has the same completeness guarantee on both
  (`open_orders` returns all of them, always). *(CONCEPTS §12·N11)*
- **V5** Trigger/conditional orders are excluded from order truth on every venue,
  stated in the schema.
- **V6** Spot's position is the wallet's base-coin holding, synthesized into the one
  position shape — the position endpoint is never called for spot. Where a venue
  keeps no basis (spot; v2's demo lesson — the reason the field exists),
  `assumed_avg_entry` serves; a venue-reported basis always overrules the config.
  Spot write bodies carry no positionIdx/reduceOnly, and market orders pin
  `marketUnit=baseCoin` so qty is base-denominated on both sides. A residue below
  the venue's minimum order qty is FLAT, never a position — spot fees settle in
  the base coin, so a full exit always leaves an unsellable shaving. *(the
  8.85e-06 LTC dust, 2026-08-05)* Under D24 the balance is SIGNED: negative is a
  short (side Sell), the dust rule is symmetric around zero, every order carries
  the venue's borrow flag (`isLeverage`), shorts are legal only under
  `spot_borrow`, and sizing flows the one normal path (`leverage :=
  spot_leverage`).

## C — config doctrine

- **C1** Unknown keys are refused at every level including nested objects; one refusal
  implementation, one exception type, one difflib cutoff.
- **C2** A rename is one commit spanning validator, readers, docs, examples, and error
  text; the old key is refused with the migration stated — never aliased. *(the capital
  pattern; the five HEAD defects)*
- **C3** Every numeric key validates type, sign, and range; fraction-valued keys share
  one interval convention.
- **C4** Derived values are written back once; an operator-supplied value for a derived
  key is refused, never silently overwritten. *(the notional lesson)*
- **C5** A config that cannot place a single order refuses at load — never a silent
  empty ladder.
- **C6** A row that fails validation refuses the whole fleet: nothing starts until the
  file is fixed — no silent skips. *(D7)*
- **C7** Every error message names only keys and values that exist.

## X — stops

- **X1** A stop is the off button: firing flattens the grid's inventory, cancels every
  owned order, kills the bot, and prevents restart. Opt-in per bot, restable anywhere
  the venue allows. *(D1, D3 — deliberately overturns v2's stand-down-only stop)*
- **X2** The stop rule names the quantity it watches:
  `stop: {watch: mark_price | account_equity | position_sl}`; a venue-side SL the
  operator placed by hand is picked up and respected. *(D3; CONCEPTS §7)*
- **X3** Server-side is the preferred implementation: its own opt-in key, refused where
  the venue cannot host it, sized to respect X6 (partial-SL where supported, bot-side
  flatten otherwise). *(the liquidation study's #1 TAKE; D3)*
- **X4** Every stop/kill path states what still rests on the venue after it — in its
  event, and in spec.
- **X5** Flatten-and-kill uses the same paginated truth read as everything else; only
  owned orders are cancelled. *(the cancel_all divergence, CONCEPTS §12·N1)*
- **X6** Stop scope is grid inventory only: the `min_position` floor core survives a
  stop. *(D2)*
- **X7** A fired stop survives the process: the tombstone is durable BEFORE the
  flatten (a crash mid-stop stays dead), a tombstoned botid builds dead-and-visible
  (F4), and revival is a deliberate operator act — delete the entry, never automatic.
  The file fails CLOSED (corrupt ⇒ the fleet refuses to build, never a silent
  revival), but a failed WRITE never blocks the flatten itself — stopping beats
  remembering.
  The one narrow local durable fact E3 permits: the exchange cannot express "this
  bot's stop fired". *(the undesigned fifth start state, ALIGNMENT — closed
  2026-08-05)*

## F — fleet and operations

- **F1** Every bot in a fleet appears in that fleet's watchdog config; the spec fails in
  both directions.
- **F2** Watchdog position ceilings are pinned near the cap (breach ⇒ the cap itself
  failed), never derived from "held plus budget".
- **F3** One fleet process per account, ever.
- **F4** Snapshots include dead bots — liveness must be detectable from the file.
- **F5** The demo fleet can never carry the mainnet flag; the gate is per-venue and
  write-only paths need it.
- **F6** Every watchdog threshold documents its assumption set — including whether the
  grid is assumed to be the only actor on the account.
- **F7** Mainnet is double-safetied (D25): it fires only when the fleet file declares
  `"allow_mainnet": true` AND the launch passes `--allow-mainnet`. Either alone
  refuses, naming the missing half. The demo/testnet env flags are the helmet; this
  is the armour — a cloned repo cannot reach real money by accident. *(supersedes
  F5's "no mainnet path"; F5's demo-fleet clause stands)*

- **F8** The preflight (D27, optional): `probe` places ONE unfillable post-only
  rehearsal order per bot at build and cancels it — the whole placement path
  (auth, permissions, collateral, lot rules, the preconditions nobody published)
  proven before any strategy order; the metadata half refuses what the venue's
  catalogue already knows (a borrow bot on a coin whose `marginTrading` says no).
  `max_failed_bots` is the tolerance: 0 refuses the fleet (D7); within tolerance
  a failed bot builds dead-and-visible (F4) and the rest trade. *(the 170037
  incident: ~1,500 runtime warns that should have been one build refusal)*

## R — the readout

- **R1** Fill history is venue-derived and link-attributed (I1's rule: ours iff the
  rung parses), deduped by execution id (I4), every cursor followed to the end or
  refused (E5) — never a local guess of what filled. *(the exchange is the state)*
- **R2** Per-bot profit is average-cost accounting over time-ordered fills: a reduce
  realises against the basis, a flip re-anchors at the flip price — in the
  contract's own PnL coin (A4): base for inverse, quote elsewhere. *(the
  −121,570 phantom, 2026-08-05)*
- **R3** Fills owned by no bot are reported in their own bucket, never dropped —
  external activity on the account must be visible. *(F6's other half)*
- **R4** The readout is read-only by construction: no write surface appears in its
  module.
- **R5** "Grid profit" is realized minus fees (D8); "total P&L" adds mark-to-average
  on the open remainder; an unknown mark yields no number, never a guess.

## T — testing meta-invariants

- **T1** Every invariant in this file has a spec named after its ID — or after the
  D-number that minted it (both namespaces are stable; D23's specs pin M10/M11).
  A spec that passes with the behaviour sabotaged is a defect. *(audit 3.8)*
- **T2** Every loop is driven at least two iterations by some spec. *(the fleet-loop
  NameError that no spec caught)*
- **T3** The backtester drives the real `plan()`; fills require trade-through, not
  touch; funding is modelled. *(freqtrade + passivbot studies)*
- **T4** v3's `plan()` is diffed against v2's on identical fixtures before v3 places a
  single live order. *(the v1→v2 method)*
- **T5** Docs cite spec IDs; no doc asserts behaviour a spec doesn't pin. *("prose rots;
  an assertion fails loudly")*
