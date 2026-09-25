# Alignment — what a grid is, what a martingale is, and every way one starts

**Status: superseded 2026-08-04 — every ⚠ DECIDE below is resolved in `DECISIONS.md`,
and where this draft conflicts with it (notably "the bot never closes a position",
overturned by D1), DECISIONS and `SPEC.md` win. Kept for the reasoning trail.**
Written from the full v2 reading: the code dissection (`CONCEPTS.md`, PR #1), the design
docs (BOTS, DESIGN, GRID-MATHS, OPERATING), the research corpus (PRIOR_ART + five studies),
the testing logs, and the changelog/commit history. Where a claim has a source it is cited
as `doc §/line`; where something is genuinely undecided it is marked **⚠ DECIDE**.

The owner is writing a response document; this file exists to be marked up by it.

---

## 1. What a grid is

The answer already exists in v2, in three layers written down in three places. v3's job is
to state them as one definition and pin it with specs.

**The creed** (OPERATING.md §"five ideas"):

1. One stateless loop; **the exchange is the state**. Kill it mid-cycle, restart it,
   nothing is lost.
2. **It refuses; it does not adapt.**
3. **One lot per rung.**
4. **The bot never closes a position.** A "stop" means *stop trading*, never *get me out*.
   (Sole exception: a martingale round's `tp_through_market` close.)
5. **The edge is the range the operator chose.** A wrong range is executed perfectly.

**The formal model** (GRID-MATHS.md, stale names corrected):

- A fixed lattice: N tick-rounded prices spanning `[lower, upper]`, geometric or
  arithmetic, computed once. **Price never moves them.** (§1)
- The **lot**: one rung's worth of base units, from the mean rung notional. Everything —
  exit ladder, position cap, entry suppression — counts in lots. (§2–3)
- The **split**: the tradeable reference (book mid, fallback mark) divides rungs into
  entries and exits; the exit floor is the *larger* of the reference and
  `basis × (1 + markup)` — the grid refuses to sell at a loss. (§4–5)
- The **exit ladder**: cover the net position one lot per rung, nearest first; the
  farthest eligible rung absorbs a 0.5–1.5-lot remainder. Inner rungs never move; a fill
  is a surgical add/remove of one rung. (§6)
- The **window** governs placement only, never cancellation. (§9)
- Income ≈ round-trips × lot value — **the spacing cancels**; spacing chooses trip
  frequency vs trip size, not income. (§12)

**The settled structural decision** (recurring-bugs-and-prior-art.md, 2026-07-20 —
*this was decided explicitly, with evidence; it is not open*):

The field splits into Camp A (per-cell paired state machines: each buy remembers its
paired sell — Hummingbot Grid Executor, 3Commas, Binance, Bitsgap) and Camp B (netted:
re-derive the whole ladder from the net position every cycle — passivbot, v2). v2 chose
**Camp B**, because Camp A is more local state plus a reconciler — the exact machinery the
truth/plan/apply architecture exists to delete — and because the tested claim in Camp A's
favour (pairing prevents loss-making exits) was refuted 0-for-3 once the venue nets the
position anyway. v2 *tried* cell-pairing first (test #2, 2026-07-23) and replaced it.
Camp B's known cost — the bot may sell at cost — is priced in via the exit floor.

BOTS.md §5c still carries the cell-paired sentence ("buy rung i, sell at rung i+1") six
lines above the netted paragraph; the backtester's profit attribution still pairs cells.
v3 states Camp B once and deletes the residue.

**The owner's invariant, earned twice** (grid.py:414, spec_plan, 2026-08-02):

> *Entry fills should only be replenished when their corresponding exit has been filled.*

This is the entry-side one-lot-per-rung. It was deleted (2026-08-01, "the cap is the
bound") and restored one day later after a live grid stacked one rung five times — nine
entry fills, zero exit fills, a position built from flat in 12h with nothing
round-tripping. Its three generations (inferred `occupied`
→ absent → observable arming-order prefix-skip) are catalogued in CONCEPTS.md §6.4. In v3
this invariant belongs in the definition, not in a code comment.

Proposed one-sentence definition for v3, to be marked up:

> **A grid is a fixed lattice over an operator-chosen range with a budget divided across
> it, run by a stateless loop that each cycle re-derives from the venue's net position the
> ideal ladder — entries below the reference, exits above the basis-protected floor, one
> lot per rung on both sides, a rung's entry never re-arming while its lot is unexited —
> and applies only the difference. It idles outside its range, refuses what it cannot
> verify, and never closes the position.**

---

## 2. What a martingale is — one open decision

Settled and matching the proposal (BOTS §6b): one direction; a fixed ladder from
`first_entry` to `lower`, placed once, windowed, **not** trailing (a deliberate divergence
from passivbot, the only prior art — theirs trails); no per-rung harvest; the round's only
exit is the whole-position TP; `repeat` re-anchors from flat, which is safe *because* flat;
absolute TP refused alongside `repeat` (the 2026-07-31 stale-target incident: a "take
profit" below the round's own realised average).

**⚠ DECIDE — sizing semantics.** The owner's definition (BOTS §6b, verbatim): "each step a
multiple **of the previous order's volume** — e.g. 2x / 1x / 3x." The build: weights
normalised to the **total** (`notional × wᵢ/Σw`). These disagree: `[2,1,3]` as built makes
step 2 *half* of step 1. BOTS records both, six lines apart, without reconciling.

The evidence favours the build's semantics, for one reason: normalised weights are an
arithmetic invariant — total exposure is the budget, by construction, no terminator needed.
That is precisely the sizing property the liquidation study demands
(liquidation-and-risk.md: "converts a real-time race you lose into an arithmetic invariant
you cannot violate"). A multiple-of-previous progression is open-ended and needs an
external cap. Recommendation: **keep normalised-to-total, and rename so the config stops
implying multipliers** (the audit's `level_weights` name survives; the README's "the
classic 2x/1x/3x progression" prose does not). If the owner wants to *write* multipliers,
a validator can accept them and normalise — sugar, not semantics.

Also carried from the dissection: the martingale currently cannot express a position
floor/ceiling or any churn damping (none of those keys are legal on its rows), the round-2
TP has **never been observed on fixed code**, and the absolute TP is dead code today
(CONCEPTS §12 N0e). v3 decides whether the missing keys are gaps or intent.

---

## 3. The start states

Four, not three — restart is a start state and the best-tested one.

### 3a. Flat
No position, no orders. The original migration decision (DESIGN §7: "leaning flat").
The whole adoption family — deadband, ratchet, basis clamps — is **inert by construction**
from flat (verified: the ratchet returns the config by identity). Ladder = all entries.

### 3b. Seed — ⚠ DECIDE (mechanics were never designed)
The term is the owner's own: *"starting from flat or seed, deadband and the other adoption
cases would be false."* So its meaning is already fixed: **a position the bot itself opens
at (or near) the mark at start, so basis ≈ mark and the adoption family stays inert.**
What was never designed, anywhere (and the research corpus never studied — a genuine gap):

- **Size.** The natural answer is already in the spot-stack configs' sizing doctrine:
  one lot per rung on the exit side of the mark — the ladder starts perfectly covered,
  no remainder dump. (fleet.demo.json `_note`: "the sellable excess equals the rungs above
  spot and the buy headroom equals the rungs below it.")
- **Order type.** Market (pay taker, guaranteed basis ≈ mark) vs limit (maker, may not
  fill — and a half-filled seed is an adoption with a worse story).
- **Failure.** Partial fill, or seed rejected: refuse to start, or degrade to flat?
- **Restart discrimination.** A restart must not re-seed. The seed must be observable as
  "already done" from the venue alone (the position exists), consistent with the
  exchange-is-the-state rule — which argues the seed is *not* config (`seed: true` would
  re-fire), but a start *mode*.

### 3c. Adopt
Point the grid at a position it didn't build. Built, proven (the mainnet HL fleet was
re-cut to adopt the owner's real positions, 2026-07-31), and the netted model's weakest
point: one venue average, no per-rung history. The earned rules:

- Basis: venue average always wins; `assumed_avg_entry` is the Bybit-spot-only fallback
  ("config beats a guess" — born from the mid-tracking churn incident). Never invent a
  basis; never fabricate fills to explain a position (research REJECT: a bot with a
  position it cannot explain has a bug — halt and alert).
- The floor (`min_position_base`) is what makes tight ranges possible over a stack, and
  the cap is measured against *held* while sellable is *held − floor* — conflating them
  cost a day of over-accumulation (the overnight cap failure; only the watchdog's per-bot
  position bound could have caught it).
- The exit ladder must start within ~one rung of the mark (the ~3%-dead-band
  lesson, pinned in spec: "the dead band was never about entries — it was the exit ladder
  starting 2.99% away").
- Over-cap adoption (position > full ladder): entries fully suppressed is correct;
  exits still cover. Under-one-lot: dust — today folded by rounding; state it.

### 3d. Restart
Position *and our resting orders* exist. Orders re-adopt by identity (`{botid}-{rung}-`
prefix; proven twice live with zero churn); position adopts implicitly (plan is pure over
truth); the martingale TP adopts explicitly (the restart-flattens-a-round fix). But **all
in-memory state silently resets**: cooldowns (a crash-loop defeats both churn guards), the
sticky ref, the deadband ratchet, trail bounds (~2 minutes of ladder in the wrong place),
the round counter display. v3 decides per item: is reset acceptable (document it), or must
the quantity be derivable from the venue (prefer this — it is the exchange-is-the-state
rule applied uniformly)?

### ⚠ DECIDE — the fifth state nobody chose: involuntary flat
BOTS §6a promises "position → 0 → the bot kills itself." **No such path exists** for a
grid (CONCEPTS §12 N14). Since no shipped config sets a `stop`, the real behaviour today:
your exchange-side stop fires, the venue closes the position, and the still-alive grid
lays a fresh entry ladder into the move that just stopped you out. Options:

1. **Idle-and-page**: on position → 0 *not caused by our exits*, stand down entries, page,
   wait for the operator. (Distinguishable: our exits carry our link prefix; a stop/manual
   close does not.)
2. **Kill**: implement the documented promise.
3. **Re-enter** (today's behaviour): defensible for a range thesis, but then the docs must
   say so and the stop story must say "a stop does not end the grid."

Recommendation: (1) — it is "it refuses, it does not adapt" applied to an unexplained
position change, and it needs no new config.

### The scenario matrix (for the spec suite, one row each)
Axes: start state {flat, seed, adopt, restart} × mark {inside, above upper, below lower}
× basis vs mark {in-profit, underwater, none} × position vs ladder {0, <1 lot, n lots,
>cap} × venue basis {reported, absent} × foreign orders {none, present}. Most cells
collapse; the ones that don't are exactly the incidents v2 hit live (the 2.99% band, the
sell-only stack, the boundary flip) plus the undefined ones (flat-below-range rests
nothing; involuntary flat; seed partial fill). The v3 spec suite should name every
non-collapsing cell.

---

## 4. Standing corrections to carry (so this doc doesn't rot the same way)

- The CHANGELOG stops at 2026-08-01; the occupancy deletion, the one-lot restoration and
  `investment`→`capital` live only in commit bodies and spec docstrings. **Code and specs
  are the truth; every v2 prose doc is somewhere behind.**
- The research corpus never studied exit models, seeding, or martingale sizing; BOTS'
  "Hummingbot/infinity-grid model" and `double_down_factor` attributions are unsourced.
  Camp B stands on v2's own tested reasoning, which is better anyway.
- The liquidation study's #1 recommendation — a **server-side stop resting on the venue**
  (survives process death) — was never built; `apply_stop` was never called and is
  deleted. v2's `price`/`equity` stops die with the process. v3 should treat this as a
  requirement with its own opt-in key and refusals (it must never touch the
  `min_position_base` core; HL refuses the endpoint; hedge mode must pick a leg).
- "Kill is not a risk control": a dead bot leaves orders and position live. Every v3
  stand-down path must say what still rests on the venue after it.
