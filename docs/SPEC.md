# SPEC — the invariants

**Status: skeleton draft, 2026-08-03. Numbering is stable from this commit on** — cite
IDs in reviews, commits, and conversation. Each line is one statement that is true or
false, with its source (an incident, a decision, or a study — see `research/`). The
`test:` column stays empty until the slice that builds it lands; then the spec test is
named after the ID. ⚠ DECIDE marks the owner's open calls (mirrors `ALIGNMENT.md` §13 +
`LEAN.md` §4); those lines are drafts of *both* options' shape, not decisions.

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
  stand-down happens only by stop rule or operator.
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
- **G4** The lot is the one canonical inventory unit: exit ladder, cap headroom, and
  entry suppression all count in the same lot. ⚠ DECIDE its anchor — ref-priced,
  nearest-exit-priced, or one rule for both states. *(CONCEPTS §12·N2)*
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
- **G11** Out of range the grid idles — it never chases and never dies on its own.
  *(§5d; field consensus, LEAN §4d)*
- **G12** The engine is netted (Camp B): the ladder re-derives from the net position;
  no per-rung paired state exists anywhere. *(decided 2026-07-20; ALIGNMENT §1)*

## W — the window

- **W1** The window limits placement, never cancellation.
- **W2** One named window anchor, used by every consumer — no raw-vs-sticky split
  between the window and the planner. *(audit 3.4; CONCEPTS §12·N4)*
- **W3** A resting, still-planned order outside the window is left alone.

## B — bands and churn guards

- **B1** One mechanism per boundary, one name each — the no-trade band (basis), the
  split hysteresis (ref), the trail snap band; "deadband" and "hysteresis" appear
  unqualified nowhere. *(ALIGNMENT §13.6)*
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
- **B9** ⚠ DECIDE whether the configurable no-trade band family survives at all — no v2
  config ever set it; if it survives, the entry edge never tightens under a resting
  ladder (the ratchet property), stated as a spec not a mechanism.

## M — the martingale

- **M1** The martingale is the grid's ladder math run with different data: one
  direction, cumulative-prefix suppression, no per-rung exits — one implementation,
  zero duplicated formulas. *(audit 3.2/3.3)*
- **M2** The config speaks the field's language — `size_multiplier` (of the previous
  order) and `max_additions` — and the validator expands the series, refusing any
  ladder whose total exceeds `capital`, stating the number in the error. *(LEAN §4b;
  pending owner confirmation)*
- **M3** A round is never without an exit: the whole-position TP is set before the
  round rests, and a target the market has run through closes at the target or better
  via reduce-only marketable limit. *(the stale-target incident)*
- **M4** ⚠ DECIDE the TP basis: the round's anchor (v2) or average entry (the whole
  field) — named into the key either way. *(LEAN §4c)*
- **M5** `repeat` re-anchors only from flat; an absolute TP is refused alongside it.
- **M6** Round state is venue-derivable: a restart adopts the resting TP and never
  rewrites a live round's exit. *(the restart-flattens-a-round incident)*
- **M7** ⚠ DECIDE whether the martingale gains the grid's floor/cap and churn-damping
  keys, or their absence is documented intent. *(ALIGNMENT §13.9)*

## S — start states

- **S1** From flat, every basis-anchored mechanism is inert by construction — verified
  by identity, not by tolerance.
- **S2** Seeding is observable as already-done from the venue alone; a restart never
  re-seeds.
- **S3** The seed is one lot per exit-side rung, so the ladder starts covered; ⚠ DECIDE
  order type and the partial-fill/failure policy (field precedent: market order, refuse
  to start on a failed seed). *(LEAN §4a)*
- **S4** Adopting: the venue's basis always wins; a basis is never invented, fills are
  never fabricated, and a position the bot cannot explain halts and alerts. *(nautilus
  REJECT of phantom orders)*
- **S5** An adopted basis beyond the range means no exits, one warning, and the position
  left to the operator.
- **S6** A restart re-adopts resting orders by identity with zero churn; every quantity
  that does reset on restart is on a named list with its consequence stated.
- **S7** ⚠ DECIDE involuntary flat — position → 0 not caused by our exits:
  idle-and-page (recommended), kill, or re-enter. Whatever is chosen, it is a spec, not
  an accident. *(ALIGNMENT §3)*
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
- **C6** ⚠ DECIDE row-failure policy: refuse the fleet or explicit skip — v2 skips
  silently, which removed live grids on a typo.
- **C7** Every error message names only keys and values that exist.

## X — stops and stand-down

- **X1** "Stand down" (the bot stops trading) and "stop-loss" (the venue closes the
  position) are different words everywhere in config, code, docs, and events.
- **X2** The stand-down rule names the quantity it watches:
  `stop: {watch: mark_price | account_equity | position_sl}`. *(CONCEPTS §7; pending
  the §13.4 restructure-vs-rename call)*
- **X3** A server-side stop-loss is its own opt-in key with its own refusals: it never
  covers the floor core, and it is refused where the venue cannot host it. *(the
  liquidation study's #1 TAKE; stops.py's own warning)*
- **X4** Every stand-down path states what still rests on the venue after it — in its
  event, and in spec.
- **X5** Stand-down cancels only owned orders, through the same paginated read as truth.
  *(the cancel_all divergence, CONCEPTS §12·N1)*

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

## T — testing meta-invariants

- **T1** Every invariant in this file has a spec named after its ID; a spec that passes
  with the behaviour sabotaged is a defect. *(audit 3.8)*
- **T2** Every loop is driven at least two iterations by some spec. *(the fleet-loop
  NameError that no spec caught)*
- **T3** The backtester drives the real `plan()`; fills require trade-through, not
  touch; funding is modelled. *(freqtrade + passivbot studies)*
- **T4** v3's `plan()` is diffed against v2's on identical fixtures before v3 places a
  single live order. *(the v1→v2 method)*
- **T5** Docs cite spec IDs; no doc asserts behaviour a spec doesn't pin. *("prose rots;
  an assertion fails loudly")*
