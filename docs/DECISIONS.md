# Decisions — frozen 2026-08-04

The owner's answers to every open call from `ALIGNMENT.md` §13, `LEAN.md` §4 and
`SPEC.md`'s ⚠ markers, organised from the owner's written response plus a four-question
follow-up. **From this file on, these are settled — the migration map and the build do
not relitigate them.** Where I interpreted an answer, the interpretation is flagged and
stands unless the owner corrects it.

## The engine

- **D1 — A stop is the off button** *(S7, X)*. A fired stop **flattens the position,
  cancels every owned order, kills the bot, and prevents restart**. A position fully
  closed from outside (manual market/limit close — detected as a flat position not
  caused by our exits) ends the bot the same way: cancel, kill, page. This deliberately
  overturns v2's "the bot never closes a position"; the owner's words: *"the idea that a
  bot can never close out a position is a false assumption."*
- **D2 — Stop scope: grid inventory only.** On a bot with a `min_position` floor, a stop
  flattens down **to the floor** — the long-held stack survives. Server-side stops must
  respect this (partial-SL sized to inventory where the venue supports it; bot-side
  flatten otherwise).
- **D3 — Stops are opt-in, restable anywhere the venue allows**, and a venue-side SL the
  operator placed by hand is picked up and respected (`watch: position_sl`). X2's
  `stop: {watch: mark_price | account_equity | position_sl}` restructure: **approved**.
  Server-side as the preferred implementation (X3): **approved**.
- **D4 — The replenish rule is the law of both strategies** *(G7)*: an entry is never
  replenished until its corresponding exit has filled. Owner's example: a 63,000 buy
  with its sell at 63,500 does not re-arm at 63,000 until the 63,500 exit fills.
- **D5 — The lot has one anchor: the split ref, always** *(G4)*. No state-dependent
  re-pricing.
- **D6 — No configurable deadband** *(B9)*. The dissolving no-trade behaviour the owner
  described — entries inside the band release furthest-from-mark first as exits fill,
  converging on average entry — **is exactly what D4 + the floor + the fee floor
  produce**, so it ships as emergent behaviour with zero keys. `no_trade_pct`,
  `entry_deadband_pct`, `exit_deadband_pct` and the ratchet are retired. The 0.1% fee
  floor stays a constant.

  *Why adoption is safe without the knob* (owner asked, 2026-08-04). Normal operation
  places only post-only limits — market orders exist solely in the seed and the
  stop-flatten — so nothing can offload or load inventory "at market"; the question is
  only where limits may rest, and three invariants answer it:
  1. **Adopt in profit** (basis below mark): the exit floor is `max(ref, basis×1.001)`
     and ref wins — every exit rests *above* the current price, one lot per rung,
     nearest ~one rung up. No dumping. Re-buying the rungs the position already
     occupies is blocked by the replenish prefix (G7): the nearest `held-lots` entries
     are suppressed and release furthest-first as exits fill — the owner's dissolving
     band, converging on the basis. The cap bounds accumulation regardless.
  2. **Adopt underwater** (basis above mark): the basis wins the max — exits rest only
     above `basis×1.001`; basis beyond the range ⇒ no exits, one warning, position
     left to the operator (S5). The zone between mark and basis holds *nothing by
     construction*: above ref so not entries, below the floor so not exits — the
     deadband, unconfigured. Entries below mark arm normally (buying the dip is the
     job), cap-bounded.
  3. **Autofill on placement** is blocked three independent ways: the ref split (G5),
     the basis floor (G6), and the cross guard (B3) — and post-only makes a crossing
     order a venue rejection, not a fill.
  v2's audit measured the configured exit band as inert whenever the mark-to-basis gap
  exceeded it, and no shipped config ever set the family — the emergent guards anchor
  to the actual position instead of a guessed number.
- **D7 — A bad fleet row refuses the whole fleet** *(C6)*. No silent skips; nothing
  starts until the file is fixed.

## The grid

- **D8 — Input model confirmed**: `{upper, lower, rungs, capital}`; spacing derives.
  The Bybit/Pionex per-grid profit reporting model (grid profit vs total P&L) is the
  one users understand — adopt it.
- **D9 — Seeding is a config toggle for flat starts** (irrelevant to adoption). Seed by
  **market order**, sized by bounds + mark: the lower in the range the mark sits, the
  larger the seed, covering **all** exit-side rungs. Windowing governs which exits
  *rest*, never how much is seeded (the Pionex shape). On failure: refuse and retry.
  *Interpretation confirmed by the owner 2026-08-04.*
- **D10 — Trail is deleted.** Range edits through the normal diff give trailing for
  free when wanted; the SMA machinery goes. Infinity-grid-style behaviour is likewise
  covered by editing bounds. (Owner note for the ops layer: routine range-review can be
  an agentic health-check task rather than engine code.)

## The martingale

- **D11 — 3Commas vocabulary and semantics adopted**: `base_order` + `safety_order` +
  order-size multiplier (of the previous order) + `deviation` +
  `deviation_step_multiplier` + `max_averaging_orders`; TP-basis switch exists but
  **defaults to average entry** (D12). The validator expands the full series and refuses
  any ladder whose total exceeds `capital`, stating the number (Binance-style).
- **D12 — TP measures from average entry** *(M4)*, recomputed as fills deepen. Not
  Bybit's %-of-investment model — owner: "i dont like how bybit calculates it."
- **D13 — The martingale has no range bounds.** Under D11 the ladder's depth derives
  from the deviation schedule × max orders — there is no `lower` key to name, which
  dissolves naming question #12 (the owner's instinct was right: they're *safety/
  averaging orders*, and that is what the field calls them). The grid keeps its bounds.
- **D14 — No floor/cap/damping keys for the martingale** *(M7, resolved by D11)*: the
  cap is the refused-if-over-capital series, a floor is meaningless under a
  whole-position TP, and damping guards a boundary the martingale doesn't have.
  Absence is derived, not missing.
- **D15 — Staged, not skeleton** *(owner may pull any forward)*: partial TPs, trailing
  TP, signal start-conditions, profit reinvest, cooldown-between-rounds tuning.

## Naming and structure

- **D16 — Position ceiling keeps the unit in the name** (`max_position_base` form).
- **D17 — Martingale ladder vocabulary dissolves under D11/D13** — `levels`/
  `level_weights` leave the config surface entirely.
- **D18 — The one-sentence grid definition (ALIGNMENT §1) is approved**, amended by D1:
  the final clause becomes "…idles outside its range, refuses what it cannot verify,
  and closes the position only when its stop says so."

## The build

- **D19 — Bybit first, Hyperliquid second**, once the build's shape is proven.
- **D20 — Field-note correction from the owner**: Pionex *does* ship a futures
  martingale/DCA product, available only in their mobile/tablet app — recorded against
  `research/field-martingale-bots.md`'s "not confirmed."

- **D21 — HL martingales via the venue-resting exit (2026-08-04).** M3 generalises:
  *a round is never without a venue-resting exit* — a hosted position-TP where the
  venue offers one (Bybit keeps its native TP: arguably stronger), a resting
  reduce-only limit at the target elsewhere (HL). The choice is a client
  *capability* (`hosts_position_tp`), never a venue-name test — the bot stays
  venue-blind. Rung 0 of a round is reserved for the resting exit and shielded from
  the diff. A resting-limit TP fills on trade-through rather than mark-trigger —
  at the target or better, accepted.

- **D22 — 1s polling instead of WS wake (2026-08-05).** The owner's call on the
  WS-wake question: raise the poll to 1s fleet-wide. The venue's rate budget is
  the real pace — the Bybit glide and HL's 429-sleep stretch a nominal 1s to
  whatever the venue allows — so "1" means "as fast as permitted", with zero
  new moving parts. WS wake leaves the backlog; it can return as its own
  decision if 1s proves insufficient for tight grids.
- **D23 — Martingale partial TPs and trailing ride the venue (2026-08-05).**
  The owner: "utilise bybit's exchange side options… do what we did for the
  full TP logic, except partial." Same doctrine as D21: venue-hosted where the
  venue offers it (Bybit's Partial tpslMode / trailing stop), the resting
  reduce-only ladder where it doesn't (HL: partial TPs are simply several
  rung-0-style exits at tranche prices). Staged next; D15's list shrinks.

*Source documents: the owner's response file (local), the 2026-08-04 Q&A, and the
2026-08-05 morning directives. Scrutiny was invited; scrutiny applied is recorded
inline above.*
