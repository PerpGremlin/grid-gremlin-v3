# Agent report: strategy math (grid.py, martingale.py, window.py, trail.py, backtest.py, plan.py)

$V2 = /home/perpgremlin-/dev/projects/grid-gremlin-v2

## PREMISE CORRECTION
One-lot-per-rung was NOT replaced — deleted 2026-08-01, RESTORED 2026-08-02 in non-inferential form.
- Gen 1 (→08-01): `occupied` set — inferred which rungs held lots as "n rungs nearest avg entry". Tombstone grid.py:307-339. Killed by: blanked a ~3% stripe across the mark on an adopted position (07-31).
- Gen 2 (08-01→08-02): absence — cap+lots_free only; a rung could hold many lots. Killed by: live grid, 12h — one rung re-armed+filled FIVE times, nine entry fills zero exit fills, position stacking from flat (recorded grid.py:410-415).
- Gen 3 (08-02→now): `n_held` prefix-skip — entries[n_held:], n_held = round(abs(total)/lot), anchored on ARMING ORDER not average, entry side only.
Gen-3 residuals: rung can still hold >1 lot if n_held undercounts (partial fills); n_held counts `total` (above min_position_base) so a grid over a pre-existing stack with no floor suppresses its whole entry ladder permanently (documented :431-435); under arm_order=furthest the OUTER rungs are suppressed (spec_plan.py:1395-1400); lots_free counts `held` while n_held counts `total` — two denominators; martingale equivalent is structurally different (cumulative prefix test `pos_size >= cum-1e-12`, martingale.py:59, counts raw held, no floor concept).

## Concepts (name → all v2 aliases; unit; evidence)

### Price lattice
- Lattice builder grid_rungs() (grid.py:26-38): N prices [lower,upper] inclusive, geo/arith, tick-rounded; N<2 → [round_price(lower)]. Aliases for the list: prices/rungs/RUNGS/_erungs/LIVE_RUNGS etc.
- Bounds: lower/upper/L/U/lo/hi; _lower/_upper (trailed current) vs _resting_lower/_resting_upper (home).
- Count: rungs (grid) / levels (martingale) / N / steps (validator local).
- Spacing: spacing_pct config; derive_spacing (config.py:411-419, divisor N−1); derive_count (:422-429, floor 2); `spacing` in _apply_hysteresis = MIN gap not mean (bot.py:314).
- spacing_type percent/fixed (SPACING_MODES config.py:14).
- martingale_levels() (martingale.py:21-29): index 0 = first_entry end; reversed for long.
- first_entry (config) vs _entry (live round anchor, bot.py:104).

### Reference price variants
- mark (exchange mark; can sit wrong side of book) / bid / ask.
- ref = book mid (bid+ask)/2, fallback mark (bybit truth.py:165, HL truth.py:165) — "the tradeable split reference".
- plan's ref = truth.get('ref') or truth['mark'] — raw or sticky depending on caller.
- _sticky_ref: see dossier below. Local var in _apply_hysteresis holding a ref is named `mark` (misnamed).

### Money/size
- capital (config) = margin committed; effective_leverage() (config.py:156-164; spot 1× unless spot_borrow); notional = capital × eff_lev — DERIVED AND WRITTEN BACK by validator (config.py:180), read by plan as inv. `investment` refused with bespoke RENAMED message (config.py:59-64).
- _rung_notionals() (grid.py:117-137): inv*wi/total or inv/N. rung_sizing equal/weighted; rung_weights; geometric_weights (config.py:403-408).
- level_weights/mults (martingale.py:41-42).
- THE LOT (grid.py:266-277): canonical unit; from MEAN rung notional; see D2 — priced at ref when flat, RE-PRICED at exits[0][1] when holding.
- _position() (grid.py:41-45): per-side position with avg entry.
- held = round_qty(pos_size) (:258); total = sellable excess = round_qty(max(0, held−min_position_base)) (:259-265).
- min_position_base (floor; config.py:349-355); max_position_base (ceiling; 'unbounded' sentinel = none; OMITTED = full-ladder sum, grid.py:370).
- lots_free = int((cap−abs(held))/lot + 1e-9) — counts held (:371-379).
- n_held = int(round(abs(total)/lot)) — counts total (:436).
- cum (martingale prefix sums).
- avg entry aliases: avg/avg_entry/a/basis/venue_avg/assumed_avg_entry (spot-only fallback)/cost_basis(error text)/cb.
- adapter: qty_from_notional (linear n/p, inverse n [1 contract=$1], spot n/p); round_qty/round_price (floor to step / round to tick); meets_minimum (min_qty+min_notional).

### Deadband family
- no_trade_pct (unified band, fraction of avg); entry_deadband_pct legacy entry half (larger wins: dead = max of the two, grid.py:199,202).
- exit_deadband_pct: config key that is NEVER operator-intended — written by _ratchet_deadband every cycle (bot.py:381), validated as operator key anyway (D13).
- exit_markup_pct legacy exit half; EXIT_MARKUP_PCT = 0.001 fee floor constant (grid.py:17); markup = max(config_markup, 0.001, exit_dead) (:210-211). Explicit exit_markup_pct: 0 silently raised to 0.001 (L8).
- exit_against average/rung (EXIT_BASES); internal bool still called `cell` (grid.py:212). rung → exit_floor = ref outright — bypasses fee floor AND exit deadband (:214).
- Four edges: exit_floor/exit_ceil/entry_ceil/entry_floor (:214-223):
  long: exit_floor = ref if cell else max(ref, avg*(1+markup)); entry_ceil = min(ref, avg*(1−dead)) if (dead and avg) else ref
  short mirrors.
- Ratchet _ratchet_deadband (bot.py:320-381): stores loosest-ever ENTRY edge as ABSOLUTE price (_deadband_hwm), converts back to fraction vs current avg (eff = 1−hwm/avg long); fraction MAY GO NEGATIVE and must be allowed (clamping at 0 drops the band via the `if (dead and avg)` guard — spec_deadband.py:220-235). Returns planconfig by identity when dead<=0 or avg<=0. Writes no_trade_pct+entry_deadband_pct=eff, exit_deadband_pct=unratcheted dead. Exit edge deliberately NOT ratcheted — max(ref,…) dissolves it statelessly.
- Known trap pinned not fixed: exit band smaller than mark-to-basis gap is inert (ref wins the max) — spec_deadband.py:297-306, grid.py:184-188.

### Ladder split & emission (plan_grid walkthrough)
2a read: ref/side/rungs/rung_notional/pos/avg(spot fallback assumed_avg_entry)/spot.
2b edges (above). 2c entries & exits both sorted nearest-ref-first. 2d _placeable_exits prune (guard = max(spread, 5bps of mid); already-resting exempt; no book → no-op).
2e exit ladder: lot from mean_notional at ref (:273), re-priced at exits[0][1] if total>0 and exits (:275); lot<=1e-12 → lot=total; loop: dump = remaining<=lot*1.5 or last; share=round_qty(...); meets_minimum → kept else fold onto kept[-1]; post-loop leftover folds onto kept[-1] (three fold paths, D12).
2f cap/headroom (above). 2g arm_order furthest: partition on ref*(1±place_within_pct) — SLICE USES STICKY REF (inside plan) — emit reversed(inside)+outside. 2h entries[n_held:], lots_free gate, meets_minimum. 2i exits reduce_only = not spot.
plan_martingale (martingale.py:32-67): levels; inv = config['notional'] with NO capital fallback (asymmetric with grid — KeyError on unvalidated row, D3); one-lot-per-LEVEL via cumulative prefix; wrong-side-of-ref skip; NO exits ever (TP handled bot-side).

### Window
- window() (window.py:10-13, 4 lines): ± place_within_pct band around anchor; param named `mark`, docstring says mark — every live caller passes ref (L7).
- Anchors by call site: bot.py:240 RAW ref (not sticky, commented); grid.py:402 STICKY ref; backtest.py:105 bar-open mark; main.py:143 + hl/__main__.py:165 raw ref.
- Place windowed; cancel NOT windowed (diff against full desired) — spec_window.py:71-97.

### Trail
- sma() (trail.py:25-31; local `window` shadows module name, D10); sma_periods config.
- trailed_bounds() (:34-48): re-centre fixed width on target, clamped to trail_min/trail_max; `deadband` param DEAD — live path passes 0.0 (D9; only spec_trail passes non-zero).
- trail_target() (:51-72): three zones — breakout→trail; comfortably inside→snap home; edge band→hold. hyst = TRAIL_SNAP_HYST 0.05 fraction of range width.
- _apply_trail (bot.py:269-287).

### Indexing conventions
- Grid: index 0 = lowest price, always ascending, 0-based, side-independent.
- Martingale: index 0 = first_entry end (top for long — levels[::-1]), emitted order field still `rung` (holds a step).
- Weights: grid index 0 = lowest price; martingale index 0 = first entry step. Audit 3.2 understated: grid [5,4,3,2,1] ≡ LONG martingale [1,2,3,4,5] but ≡ SHORT martingale [5,4,3,2,1] (side-conditional reversal).
- Backtest cell pairing: long exit i pairs entry i−1; short i+1, clamped (backtest.py:66-71). Fill test = strict trade-through, never touch.

### Backtest quantities
grid_profit_usd (matched cells, always +); realized/realized_usd (avg-cost); total_pnl_usd = grid + floating (can be neg while grid +); net_pnl_usd −fees −funding; equity/peak/max_dd; _notional_usd (inverse contracts are USD). Backtest never exercises spot path (is_perp check; synthesised truth always orders:[] so _placeable_exits no-ops) — L11.

## Sticky ref dossier
_sticky_ref (bot.py:119): remembered price, None init, in-memory, reset on restart. Moves only when abs(mark−sticky) > band, band = MIN rung gap × split_deadband_rungs (:314-316); SNAPS to current value (not follows). Gates: frac<=0 → passthrough; <2 rungs → passthrough; martingale → never called. Config range [0,0.5].
Consumers (of plantruth['ref']): the four split edges; lot-when-flat; arm_order furthest partition; (_ratchet_deadband receives plantruth but reads only positions).
Non-consumers (raw ref): window() in cycle, _would_cross (bid/ask direct), main.py:143, backtest (bar open).
spec_hysteresis: ±40¢ jitter (5.9% of rung) → >10 rewrites off, 0 at 0.25; 1.8-rung trend releases; 0.9× holds 1.5× releases; unset ≡ 0.

## Three mechanisms called "hysteresis" (+1 retired)
1. Sticky split ref (split_deadband_rungs, price space, entry/exit role boundary).
2. Re-churn cooldown (RECHURN_COOLDOWN 60s, time space, same boundary, entries only).
3. Trail snap-back (TRAIL_SNAP_HYST 0.05, SMA vs resting bound flip-flop).
4. (retired) window hysteresis (bot.py:557-559).
Mechanism 2's justifying comments claim "ref boundary has no hysteresis" — false on every live grid (audit 3.5; L3/L4).

## Duplicates NOT in audit (all VERIFIED unless noted)
- D1 "one lot per rung" names two live mechanisms (exit ladder one-lot grid.py:232 vs entry re-arm guard :408) plus the deleted occupied (GRID-MATHS §7) — three concepts one phrase.
- D2 lot computed twice off different anchors INSIDE one function (ref :273 vs exits[0][1] :275); comment claims one canonical lot (L1); unit changes with position state; lots_free and n_held consume the re-priced one; effects push opposite directions.
- D3 notional-per-rung formula implemented twice (grid _rung_notionals not reused by martingale; martingale lacks capital fallback).
- D4 guard band formula duplicated verbatim (grid.py:78 vs bot.py:539); constant unified 07-30, expression not; polarity keyed on bot side vs order side — equivalent only because exits oppose the bot, asserted nowhere. (= runtime agent's H.)
- D5 placement window computed three ways; audit 3.4's "mark vs ref" correction: real disagreement is RAW ref (bot.py:240) vs STICKY ref (grid.py:402); backtest uses bar open; magnitude bounded by sticky band ≤0.5 rung.
- D6 position-lookup implemented three times (+2 inline copies + main.py variant with different fallback).
- D7 _resting_exit_rungs re-implements _rung_of byte-for-byte (grid.py:107-113 vs apply.py:11-19; import would invert dependency).
- D8 _placeable_exits takes botid it never uses (vestige).
- D9 trailed_bounds' deadband param dead (live path passes 0.0).
- D10 window module vs window local in sma().
- D11 three spacing derivations: config.derive_spacing (honours type); bot.py:171 arithmetic-only (start-up warning wrong on geo grids — compares AVERAGE gap vs guard while tightest is smaller); bot.py:314 min-gap (only correct one).
- D12 three sub-lot fold paths (dump rule; sub-min fold to kept[-1]; post-loop remainder fold to kept[-1]).
- D13 exit_deadband_pct in GRID_KEYS + validated as operator key but only writer is the bot; operator CAN set it — honoured first cycle then overwritten.
- D14 (INFER) no single "this config can't place anything" check — meets_minimum silently empties ladder (spec_plan.py:213-219); startup warns only about spacing.
- D15 (INFER) spot re-churn misclassification: _apply keys "was an entry" on not reduce_only (bot.py:604) — on spot TRUE for every order, so voluntarily-cancelled spot EXITS get the 60s cooldown the comment says exits are exempt from. Same bug class the side-vs-flag fix addressed in _resting_exit_rungs.

## Comments/docs that lie (L1-L27, key ones)
- L1 grid.py:268-272 "ONE canonical lot" — false (D2).
- L2 grid.py:307-339 33-line tombstone "a rung CAN now hold more than one lot" — reversed 70 lines later (:408-437); never edited.
- L3/L4 bot.py:28-33 + :554-556 "window has hysteresis, ref boundary does not" — backwards on both halves, twice.
- L6 bot.py:6 "deterministic linkId" — gen is clock-seeded counter; restart adoption works because _rung_of discards the tail, not determinism.
- L7 window.py param/docstring "mark" — callers pass ref.
- L8 grid.py:11-14 exit_markup_pct "per-bot override" — floor silently enforced; rung bypasses all.
- L12 main.py:161 preview prints literal 'first_entry' where it means entry (blanket-rename casualty).
- L13 config.py error messages name NONEXISTENT keys throughout: rung_hysteresis, cost_basis, min_inventory, max_inventory, entry_fill, exit_basis, spacing_mode, window_pct, sizing, steps/multipliers, N/spacing — _reject_unknown refuses the key the error tells you to use.
- L14 config.py:187 validate_grid docstring: three lies in one line (spacing_mode/geo/flat).
- L15 README §15 "a rung may re-arm" — false since 08-02 (inverse of audit 3.7 row 1: README corrected in the wrong direction, then code moved back).
- L16 GRID-MATHS §7/§15/§16 still document occupied (deleted).
- L17 GRID-MATHS uses `investment` throughout + "investment is not money you commit" — key is now capital and it IS the margin; MOST DANGEROUS stale doc (a leverage-factor mis-sizing trap on any live grid).
- L18 README headline JSON example does not validate (geo/flat).
- L19 README lists exit_against "cell" (refused; internal bool still named cell).
- L20 README lists arm_order near/far (both refused).
- L21 README trail block (period/outer_lower/outer_upper) fails validation on all three keys (sma_periods/trail_min/trail_max).
- L22/L23 README compounding + martingale examples use refused `investment`.
- L24 "0.1% minimum applies regardless" — not under rung.
- L25 README assumed_avg_entry §: describes gen-1 occupied semantics; right about outcome by accident, wrong about mechanism.
- L26 REVIEW-2026-08-01 header "PROPOSAL, nothing implemented" — §2a table + §2c (capital) HAVE been applied to code (not to README/GRID-MATHS/config error text — direct cause of L13,L14,L18-23).
- L27 spec_plan.py:407-421 section heading "bounded by cap NOT one-lot-per-rung" — assertions below it test the restored guard; heading stale, six resized fixtures prove code is authoritative.

## Big picture for v3 naming
- The RENAME WAS HALF-EXECUTED: config keys+values renamed 08-01/08-02 but README, GRID-MATHS, config.py's own docstrings and error messages, and internal locals (cell, first_entry tag) were not. v2 is currently mid-migration — worst possible vocabulary state (docs teach names the validator refuses).
- Side vocabularies: long/short (config) vs Buy/Sell (orders) vs ±1 fdir (backtest) vs pside.
- window/mark/ref/sticky-ref naming knot is the core anchor confusion.
- "hysteresis" and "deadband" each name 3+ distinct mechanisms.
