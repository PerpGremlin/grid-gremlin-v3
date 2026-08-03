# Concept inventory — the dissection of v2

**Source: v2 at `79c7da3` (workstation HEAD, clean tree), read 2026-08-03.**
Method per `CLAUDE.md`: every file, every function, every variable — list the *concepts*,
give each one name with the unit in it, one sentence of actual behaviour, and every v2 name
that currently points at it. Names in **bold** are proposals for the migration map (step 2),
not decisions. `⚠ OPEN` marks a decision the owner must make. Everything below was traced to
a file:line in v2; findings that contradict the 2026-08-01 audit are marked.

Companion: `REVIEW-2026-08-01.md` in v2 (`docs/`) — its §2 rename table and six duplicate
pairs are assumed known and not restated. §12 lists what this dissection found that the
audit missed, including five live defects from one half-applied rename.

---

## 1. Money and size

| proposed | unit | one sentence | v2 names |
|---|---|---|---|
| **capital** | quote | Margin the operator commits; the validator multiplies it by effective leverage and writes the product back into the config. | `capital`, `cap`, `investment` (refused key, still taught by GRID-MATHS) |
| **ladder_notional** | quote | Position value with every rung filled = capital × effective leverage; derived, never operator-set. | `notional` (config key written by validator), `inv` (both strategies) |
| **effective_leverage** | ratio | The capital→notional multiplier; spot is 1× unless borrowing. | `effective_leverage()`, `leverage`, `spot_leverage`, `_lev` |
| **rung_notional** | quote | The slice of ladder_notional allotted to one rung: `inv·wᵢ/Σw`, or `inv/N` unweighted. | `_rung_notionals()`, `rung_notional`, `n_rung` |
| **rung_weights** | — | Normalised per-rung sizing weights; `equal`/`weighted` selects flat or explicit. | `rung_weights`, `level_weights` (martingale), `mults`, `w`, `wi`, `geometric_weights()` |
| **lot** | base | The canonical inventory unit: qty from the *mean* rung notional; everything that counts position counts in lots. ⚠ OPEN: v2 prices it at ref when flat but re-prices at the nearest exit rung when holding — the unit changes with position state (§12·N2). | `lot`, `ℓ`, `LOT`, `mean_notional` (its input) |
| **held_base** | base | Position size on our side, rounded to the lot grid. | `held`, `pos_size`, `size`, `q` |
| **sellable_base** | base | The excess above the floor — the only part the exit ladder may offer: `max(0, held − floor)`. | `total` (!) |
| **min_position_base** | base | Floor under the stack; never sold. | `min_position_base`, `floor_inv`, `F`, `min_inventory` (error text only) |
| **max_position_base** | base | Ceiling on the position; `'unbounded'` = none; *omitted* = the full-ladder sum. ⚠ OPEN: audit §2d (name vs unit-suffixed name) still open. | `max_position_base`, `cap`, `C`, `max_inventory` (error text only), the martingale `cum` ceiling |
| **lots_free** | lots | Whole lots of headroom under the ceiling, measured against `held`. | `lots_free` |
| **lots_held** | lots | Lots believed already armed-and-filled, sliced off the front of the entry list; measured against `sellable_base` — a different denominator than lots_free. | `n_held`, `n` |
| **avg_entry** | quote | The cost basis: venue-reported average entry, or the spot-only config fallback. | `avg`, `avg_entry`, `a`, `basis`, `venue_avg`, `assumed_avg_entry`, `cost_basis` (error text), `cb` |

## 2. The price lattice

| proposed | unit | one sentence | v2 names |
|---|---|---|---|
| **rungs** | count | How many prices the lattice holds. | `rungs`, `levels` (martingale), `N`, `steps` |
| **rung prices** | quote | N tick-rounded prices spanning `[lower, upper]` inclusive, geometric (`percent`) or arithmetic (`fixed`); price never moves them. | `grid_rungs()`, `martingale_levels()`, `prices`, many locals |
| **lower / upper** | quote | The lattice bounds; under trail these are the *current* bounds and a second pair remembers home. | `lower`/`upper`, `L`/`U`, `_lower`/`_upper` (current), `_resting_lower`/`_resting_upper` (home) |
| **spacing_pct** | fraction or quote | The gap between adjacent rungs; divisor is N−1. Fraction under `percent`, absolute price under `fixed` — one key, two units, selected by `spacing_type`. | `spacing_pct`, `spacing_type`, `derive_spacing()`, `derive_count()`, `step`, `ratio`, `gap` |
| **rung index** | int | 0-based position in the lattice. Grid: 0 = lowest price, always. Martingale: 0 = the `first_entry` end — *reversed for a long*. The emitted order field is `rung` either way, and weight index 0 means a different rung per strategy and per side (§12·N3). | `rung`, `step`, `i` |
| **first_entry** | quote | Where a martingale round's ladder starts; the live round re-anchors it on repeat. | `first_entry` (config), `_entry` (live anchor), `anchor` |

## 3. Reference prices — one concept short of a family

| proposed | unit | one sentence | v2 names |
|---|---|---|---|
| **mark** | quote | The venue's mark price; can sit on the wrong side of the book. | `mark`, `markPrice`, `_last_mark`, backtest bar-open |
| **bid / ask** | quote | Best quotes; several guards need both and silently no-op without them. | `bid`, `ask` |
| **split_ref** | quote | The tradeable reference the ladder splits around: book mid, falling back to mark; formula duplicated verbatim in both venues. | `ref`, `truth['ref']`, `p` |
| **held_split_ref** | quote | The sticky variant: last-seen split_ref, held until price moves more than the hysteresis band, then *snapped* (not walked) to current. Consumed by the four band edges, the flat-lot pricing, and the furthest-first partition — but **not** by the placement window, which uses the raw split_ref. Full dossier §6.1. | `_sticky_ref`, plus a local literally named `mark` inside `_apply_hysteresis` |

`window()`'s parameter is named `mark`, its docstring says mark, and every live caller passes
a ref (§12·N4). The mark/ref/sticky-ref knot is the single worst naming tangle in v2: three
anchors, four names, and the name in the signature is the one value never passed.

## 4. The band, the ladder, the guards

| proposed | unit | one sentence | v2 names |
|---|---|---|---|
| **no_trade_pct** | fraction of basis | The zone around the basis where the grid does not trade; entry half and exit half computed from one key. | `no_trade_pct`, `entry_deadband_pct`, `exit_markup_pct`, `dead`, `exit_dead`, `markup` |
| **fee_floor_pct** | fraction | The 0.001 constant an exit must always clear; a knob in name only — configured values below it are silently raised, and `exit_against: rung` bypasses it entirely. | `EXIT_MARKUP_PCT`, `exit_markup_pct` (as config) |
| **exit_against** | enum | What an exit must clear: the portfolio `average` or its own `rung`; internal boolean still named `cell`, a refused value. | `exit_against`, `cell`, `exit_basis` (error text), `eb` |
| **band edges** | quote | The four computed prices: entries only below `entry_ceil` / above `entry_floor`, exits only above `exit_floor` / below `exit_ceil`; the `max(ref,…)` clamp is what dissolves the exit half. | `exit_floor`, `exit_ceil`, `entry_ceil`, `entry_floor` |
| **entry_band_ratchet** | quote (state) → fraction | Holds the *loosest-ever* entry edge as an absolute price so an improving basis can't tighten the band under a resting ladder; re-expressed each cycle as a fraction that may legitimately go negative. The exit edge is deliberately not ratcheted. Dossier §6.3. | `_ratchet_deadband()`, `_deadband_hwm`, `exit_deadband_pct` (a config key the bot writes — §12·N5) |
| **entry re-arm guard** | lots | One lot per rung, generation 3: the first `lots_held` entries *in arming order* are skipped until their lots exit; entry-side only. Three generations of this rule existed in three days — dossier §6.5. | `n_held` prefix-skip, `entries[n_held:]`, "one lot per rung", the deleted `occupied` |
| **cross guard** | bps → quote | Don't rest an order within `max(spread, 5 bps of mid)` of the opposite quote; formula written twice, character-for-character, in planner and placer (§12·N6). | `CROSS_GUARD_BPS`, `guard`, `_would_cross()`, `_placeable_exits()`/`blocked()` |
| **resting-exit exemption** | — | A rung whose exit already rests is exempt from the cross-guard drop; detection keys on *side*, not `reduce_only`, because spot exits carry no flag. | `_resting_exit_rungs()` |
| **exit ladder assembly** | — | Sellable inventory poured one lot per exit rung nearest-first; sub-minimum and leftover slices fold into the last kept rung by three distinct fold paths. | `kept`, `share`, `dump`, `remaining` |
| **arm_order** | enum | Which end of the ladder gets scarce headroom: `nearest` or `furthest`, where furthest means outermost-inside-the-window first. | `arm_order`, `entry_fill` (error text), `ENTRY_FILLS`, `inside`/`outside` |

## 5. Window, trail, hysteresis

| proposed | unit | one sentence | v2 names |
|---|---|---|---|
| **place_window_pct** | fraction of split_ref | Only rungs within this band of the split_ref are *placed*; cancellation has no window at all — the diff cancels against the full desired ladder. Anchor per call site: raw ref (live), sticky ref (furthest-first partition), bar-open (backtest). | `place_within_pct`, `window()`, `W`, `w`, `wp`, `DEFAULT_WINDOW_PCT` |
| **split_hysteresis_rungs** | fraction of a rung | Width of the sticky-ref band as a fraction of the *narrowest* rung gap. | `split_deadband_rungs`, `frac`, `hyst`, `band`, `rung_hysteresis` (error text) |
| **trail** | — | SMA-driven range shift: breakout re-centres the bounds (clamped to `trail_min`/`trail_max`), return snaps home with 5%-of-width hysteresis; `trailed_bounds`' `deadband` parameter is dead — the live path passes 0.0. | `trail`, `sma()`, `sma_periods`, `trail_target()`, `trailed_bounds()`, `TRAIL_SNAP_HYST` |

"Hysteresis" names three unrelated live mechanisms (sticky ref, re-churn cooldown, trail
snap-back) plus one retired (window hysteresis). "Deadband" names the no-trade band, the
sticky-ref band, and a dead trail parameter. v3 must give each mechanism its own word.

## 6. The internals dossiers

### 6.1 The sticky ref
In-memory price (`bot.py:119`), reset on restart. Moves only when
`|ref − sticky| > min_rung_gap × split_deadband_rungs`, and then snaps to current — a step
function, not a follower. Gated off for martingale, <2 rungs, or fraction ≤ 0. Consumers:
the four band edges, the flat-case lot pricing, the furthest-first window partition.
Non-consumers: the placement window, the cross guard, the preview CLI, the backtester. Live
values: 0.30 on both HL grids, 0.25 on four demo grids — the `bot.py` comments claiming "the
ref boundary has no hysteresis" are false on every live grid (audit 3.5, still unfixed, in
two copies).

### 6.2 Windowing — place vs cancel
Placement is windowed (`place_within_pct` around the raw split_ref); cancellation is not
windowed at all. The asymmetric diff: `to_create` from the *windowed* set, `to_cancel`
against the *full* desired ladder. A resting entry that drifts out of the window is neither
cancelled nor re-created; a stale exit is cancelled wherever it sits. Correction to audit
3.4: the two anchors that disagree under hysteresis are *raw* ref (window) vs *sticky* ref
(furthest-first partition inside the planner) — not mark vs ref; the disagreement is bounded
by the sticky band, ≤ 0.5 rung.

### 6.3 The deadband — two halves, one key
Entry half: not floored, ratcheted (loosest-ever edge held as an absolute price; the
re-derived fraction may go negative and must be allowed to — clamping at 0 drops the band).
Exit half: floored at `fee_floor_pct` always, never ratcheted — the `max(ref,…)` clamp
dissolves it statelessly. `exit_against: rung` bypasses the exit half *and* the fee floor
outright. Known pinned trap: any exit band smaller than the mark-to-basis gap is inert.

### 6.4 One lot per rung — three generations in three days
1. `occupied` (→08-01): held rungs inferred as the n nearest the basis. Killed: blanked a
   2.99% stripe *across the mark* on an adopted position.
2. Absence (08-01→08-02): cap-only bound. Killed: hlETHs mainnet, rung 1838 re-armed and
   filled five times in 12h; nine entry fills, zero exit fills, 0 → 2.18 short.
3. `n_held` prefix-skip (current): arming-order anchored, entry-side only. Residuals: a rung
   can still hold >1 lot after partial fills; a grid over a pre-existing stack with no floor
   set suppresses its *entire* entry ladder (documented in-code); under `furthest` the outer
   rungs are the suppressed ones.
The phrase "one lot per rung" additionally names the *exit* ladder's one-lot-per-rung pour —
a different rule on the other side of the book (§12·N7).

### 6.5 Adoption — one word, four mechanisms
1. `stop: {type: "adopt"}` — see §7.
2. Restart order adoption: `diff()` keeps resting orders whose link parses to a rung under
   this bot's prefix; works because the rung prefix survives restart, *not* because ids are
   deterministic (the `gen` suffix is clock-seeded — the `bot.py` header comment lies).
3. Martingale TP adoption: first cycle with an open position reads the venue's
   `take_profit` and suppresses the bot's own TP write (one-shot). Reads takeProfit and
   suppresses; #1 reads stopLoss and kills. They must not share a word in v3.
4. Docs-sense "adopting a position": pointing a grid at a holding it didn't build (the
   `assumed_avg_entry` / `min_position_base` / `no_trade_pct` family).
There is no startup reconciliation routine anywhere — continuity is emergent from plan()
being a pure function of truth. Gap: orders orphaned by a bot *removed from the fleet* are
never reclaimed by anything.

### 6.6 truth / plan / apply — the engine's spine
**truth** (per cycle): one wallet read per venue shared by all bots, then per-bot
`read_symbol_truth` (mark, bid/ask, split_ref, funding, all-pages orders, keyed positions)
plus two injected fields — `equity` from the wallet, `position_stop` from the position.
**plan**: pure function of (config, truth) → desired orders; the bot pre-mutates both
(trail bounds / sticky ref / ratcheted band) so plan stays pure.
**apply**: pair same-(rung, side, reduce_only, *price*) cancels+creates into qty-only
amends; then cancels before creates (free margin first); then creates gated by cooldowns,
cross guard, margin backoff. Fills are detected by position delta between cycles — the
websocket is a latency hint that sets an Event and never carries state. Nothing is persisted
to disk; the exchange is the only durable state.

## 7. Stops and stand-down

A "stop" here never closes a position: firing = cancel own orders, `alive = False`, emit
`kill`. The word collides with the venue's stop-loss, the venue's TP/SL *write* endpoint
(only ever called with `take_profit=`), and a deleted function. v3 should split **stand
down** (what the bot does) from **stop-loss** (a venue price) completely.

| v2 `stop.type` | watches | one sentence |
|---|---|---|
| `price` | mark | Stand down when mark crosses an operator-typed absolute price on the losing side. |
| `equity` | whole-account equity | Stand down when account equity (not this bot's) falls to an absolute floor; duplicates the watchdog's `equity_min` in unit and meaning (audit 3.6) — engine kills the bot, watchdog pages the human. |
| `adopt` | the venue position's stop-loss field | Stand down at the same price the venue's own trigger would fire — a read-only *mirror* of the operator's on-exchange SL; takes no value. |

**The `adopt` dissection** (the thing the audit refused to name): six stateless lines.
Each cycle the bot copies `position.stopLoss` into truth and compares mark against it;
fire = the ordinary stand-down. It owns nothing, writes nothing, modifies nothing — the
venue closes the position independently; adopt only stops the bot laddering into a position
that is being closed out from under it. It cannot fire while flat (no SL on a flat
position), is inert on Bybit spot (key absent) and on **all of Hyperliquid** (truth
hardcodes `stop_loss: None` — i.e. inert on all of mainnet). The README's claim that it
also respects a hand-placed take-profit is false — it reads only the stop-loss. Why it was
unnameable: `price` and `equity` name watched quantities; `adopt` names a verb the bot
never performs. **Proposed: `stop: {watch: position_sl | mark_price | account_equity}`** —
three parallel names for three watched quantities; the bot's reaction (stand down) is the
same for all and belongs in the key, not the value.

## 8. Identity, orders, events

| proposed | unit | one sentence | v2 names |
|---|---|---|---|
| **botid** | str | 3-char category prefix + venue symbol + side initial; fleet enforces one bot per (category, symbol, positionIdx). | `botid`, `make_botid()`, `bot_identity` |
| **order link** | str | `{botid}-{rung}-{gen}`: ownership prefix + rung + restart-unique clock-seeded counter; HL packs gen into 4 base-36 chars to fit a 16-byte cloid, Bybit allows 36. The rung is what restart adoption parses; the planner's own `link_id` field is dead — never placed, shown only by dry-run, in a shape that never reaches the exchange (§12·N8). | `link_id`, `orderLinkId`, `cloid`, `make_link()`, `_gen`, `_rung_of()` |
| **ownership guard** | — | An order is ours iff its link starts with `{botid}-` and the remainder parses; implemented in `_rung_of` and re-implemented byte-for-byte in `_resting_exit_rungs`. | `_rung_of()`, prefix checks |
| **event vocabulary** | — | 17 kinds; `placed`/`cancel`/`amend` are logged but shipped only when `notify_orders`; everything else ships. | `fleet start skip placed cancel amend fill exit trail funding mmr margin backoff tp repeat kill warn ws dryrun` |
| **cooldowns** | s | Flap (placed-but-not-resting ×3 → 60s), re-churn (voluntarily cancelled entry → 60s, same dict, indistinguishable in state — §12·N9), margin backoff (30s→300s, halts growth only), uncovered warn (1800s), funding dedup, Telegram ≥3s. | `FLAP_*`, `RECHURN_COOLDOWN`, `_cooldown`, `_backoff*`, `UNCOVERED_COOLDOWN` |

## 9. The truth contract and the venue layer

There is no truth class and no schema — two venue implementations agree by convention,
pinned by one spec. The load-bearing divergences:

- **`funding_rate` changes unit per venue** — 8-hourly on Bybit, hourly on HL, same field
  name, no marker; `_detect_funding` multiplies both identically (§12·N10).
- The position dict has **three shapes**: Bybit derivative (full), Bybit spot (a wallet
  balance wearing a position costume — `avg_entry` 0.0, SL/TP keys absent), HL (TP absent,
  SL hardcoded None).
- `category` is three values for one HL bot: `'hl'` (identity), `'perp'` (adapter and
  truth), and the `'linear'|'inverse'|'spot'` enum Bybit rows must declare.
- `open_orders` means "one page of ≤50" on Bybit and "all" on HL; `Bot.cancel_all` never
  follows the cursor (§12·N11).
- HL's `read_wallet` mutates a per-cycle cache that `read_symbol_truth` depends on; Bybit's
  is a pure read. Same surface, different contract.

Layering: four names, three concepts. **venue ≈ client** (the name vs the object it
selects); **adapter** is genuinely separate (pure per-instrument contract maths: tick, lot,
minimums, qty-from-notional, positionIdx); **exchange** means both the package root and the
HL write module. Bybit is one layer deep, HL is a facade in `venue.py` wrapping two clients
that live in `client.py` and `exchange.py`. The error taxonomy (`gone`, `margin`,
`ro_capacity`, …) is the venue-neutral vocabulary the bot switches on — no kind kills; every
kind maps to retry, backoff, skip, or warn, and `ambiguous` ("the write may have landed")
suppresses even the warning.

## 10. Config doctrine — what the validator actually guarantees

The stated doctrine is *unknown keys are refused, exactly one way to say each thing, the
validator writes derived values back*. The dissection found where it holds and where it
leaks:

- **Refusal stops at the row level.** `trail` and `stop` sub-keys are never enumerated —
  the README's own (wrong) trail key names validate silently and are silently ignored, and
  `stop: {type: adopt, value: X}` ignores the value without comment.
- **`venue` and `category` are in the accepted-key set but never validated** — config.py
  only ever tests `== 'spot'`; a typoed category validates and fails later at instrument
  resolution. Fleet-level checks are a *second implementation* of unknown-key refusal with
  a different difflib cutoff (0.6 vs 0.7) and a different exception type; a bare-list fleet
  file bypasses them entirely.
- **`leverage` — the largest multiplier on order size — has no validation at all.** Zero
  silently becomes 1; a negative value produces a negative notional; a string raises a bare
  `ValueError` that `build_fleet` swallows by *skipping the row*. Meanwhile `spot_leverage`,
  which matters far less, is range-checked to [1, 10].
- **`notional` is accepted as input and unconditionally overwritten** — an operator's
  hand-set value is discarded without error, the exact silent-intent failure the refusal
  doctrine exists to prevent.
- **Fraction-valued keys use five different admissible intervals** (`[0,1]`, `[0,1)`,
  `(0,1)`, `[0,0.5]`, `(0,∞)`) with no shared helper and no stated rationale.
- **Four exception types** answer "this config is wrong": `ConfigError`,
  `VenueConfigError`, `ValueError`, `RuntimeError` — the spec suite counts only the first
  as a config problem.
- **`validate_martingale` normalises `strategy` back into the row; `validate_grid` does
  not** — so every downstream reader re-defaults `.get('strategy', 'grid')`.
- **Operator-supplied `spacing_pct` is never reconciled** with the rungs it derives
  (`derive_count` rounds); the stored number can disagree with the actual gaps, and dry-run
  prints the stale value.
- **`lower` has two incompatible meanings**: grid range-bottom (`upper > lower`) vs the
  martingale ladder's *far end*, which for a short sits *above* `first_entry` — a shipped
  demo row has `lower` higher than the entry.
- **The martingale can express almost nothing**: no `max_position_base` *or*
  `min_position_base` (audit 2e noted only the former), no `spacing_pct`, no
  `split_deadband_rungs` — its ceiling is unoverridable and it has no churn damping at all.
- **The watchdog configs have no validator whatsoever** — no key rejection, no types;
  required keys `KeyError` at point of use.

## 11. Fleet, watchdog, scripts

- Fleet loop: shared wallet read → per-bot cycle → snapshot every N → MMR ladder alerts →
  wake-or-sleep; 20 consecutive whole-cycle failures stops the fleet.
- Watchdog (external, VPS): reads the snapshot JSONL; breaches = nosnap, stale, mmr,
  equity floor, drawdown-from-peak, per-bot missing, per-bot position bounds. Pages
  Telegram, never trades; sends before persisting so a failed page re-pages. Its
  `equity_min` is audit 3.6's duplicate of the equity stop; its `mm_rate_max` overlaps the
  engine's observe-only MMR ladder; its position bounds are pinned to detect the engine's
  own cap failing.
- `.env` parsing exists three times (engine regex, watchdog split-on-`#`, relay regex);
  Telegram send exists three times (notify, watchdog, relay). Deliberate isolation in v2;
  a naming decision in v3.

## 12. Findings beyond the 2026-08-01 audit

Numbered N1… for the migration map. All traced; none re-derived from the audit.

**Live defects (v2 HEAD `79c7da3` — check against the deployed `76a702a` before panic):**
- **N0a — the fleet loop is broken at HEAD.** `main.run` reads `interval` at two sites; the
  parameter was renamed `poll_seconds`. `NameError` at the end of the first cycle, *outside*
  the per-cycle try/except. No spec drives `run()` past one cycle — a fifth vacuous-coverage
  instance in the audit-3.8 family.
- **N0b — the backtester is dead at HEAD.** `Client.kline`/`klines` read `interval`
  internally after the same rename; any call raises `NameError`.
- **N0c** — HL candles sends `poll_seconds` as the wire field name; HL expects `interval`.
- **N0d** — HL spike runner `--grid` crashes: `args.place_within_pct` vs argparse dest
  `window_pct`.
- **N0e — the absolute martingale take-profit is dead.** `config.py` validates
  `take_profit_price`; `bot.py` reads `take_profit` — the pre-rename key. The TP resolves
  to `None`, the exchange-side exit is never written, and **the round is laid with no exit
  at all** — the exact failure BOTS.md §6b declares impossible. Every config that sets it
  (`fleet.mix/tight/tight3/stress.json` — historical test fleets, no systemd unit) is
  affected; the spec asserts only that the bot dies after the round, never that the TP was
  set. `take_profit_pct` (the relative form) still works.
All five are casualties of one blanket rename applied to one side of a seam — signature but
not body, validator but not reader — the strongest possible argument for v3's
refuse-the-old-key rule *plus* specs that drive every seam end-to-end.

**The rename's blast radius, measured.** `RENAMED` (the migration-refusal table whose policy
comment says entries stay for one release) covers exactly **one** of the ~21 keys renamed in
the same commit — every other old key gets a generic unknown-key error, sometimes with a
misleading did-you-mean. Every validator error message still names the *old* key
(`spacing_mode`, `window_pct`, `rung_hysteresis`, `max_inventory`, `entry_fill`, `steps`,
`multipliers`, `loop`, …) — the validator refuses the key its own error tells you to use.

**The half-executed rename.** The audit's §2a table *has* been applied to config keys and
values, but not to README, GRID-MATHS, `config.py`'s own docstrings, or its error messages —
config errors name keys that do not exist (`rung_hysteresis`, `entry_fill`, `exit_basis`,
`max_inventory`, …), so the validator refuses the very key its error tells you to use. The
README's headline JSON examples do not validate (`geo`, `flat`, `near`/`far`, `cell`,
`investment`, the old trail keys). GRID-MATHS still teaches `investment` with the exact
opposite of the current semantics — a factor-of-40 trap on the live HL grids. The audit
header still says "PROPOSAL — nothing implemented". v2 is mid-migration, which is the worst
vocabulary state a codebase can be in, and precisely the state v3's one-commit-per-rename
rule (the `capital` pattern) exists to make impossible.

**Duplicates and mismatches feeding the naming map:**
- N1 — `_kill` and `cancel_all` are two implementations of "cancel my orders": different
  key shapes (normalised vs raw camelCase), different pagination (all-pages truth vs one
  unfollowed page).
- N2 — the lot is computed twice off different anchors inside one function, under a comment
  claiming one canonical lot; `lots_free` and `lots_held` consume the re-priced one and are
  pushed in opposite directions by it.
- N3 — rung/level index conventions: audit 3.2 understated — grid weights `[5,4,3,2,1]`
  equal a *long* martingale's `[1,2,3,4,5]` but a *short* martingale's `[5,4,3,2,1]`; the
  reversal is side-conditional on one side only.
- N4 — `window()`'s parameter and docstring say `mark`; every live caller passes a ref.
- N5 — `exit_deadband_pct` is validated as an operator key but written by the bot every
  cycle; an operator value is honoured for one cycle, then silently overwritten.
- N6 — the cross-guard formula is duplicated character-for-character (planner vs placer);
  one branches on order side, the other on bot side — equivalent only because exits oppose
  the bot, asserted nowhere.
- N7 — "one lot per rung" names two live rules (entry re-arm guard, exit one-lot pour) and
  one deleted one (`occupied`), across three docs.
- N8 — the planner's `link_id` field is dead: never placed, never diffed; dry-run prints it
  in a shape that never reaches the exchange.
- N9 — flap and re-churn cooldowns share one dict, one duration, one key; a rung cooled for
  losing a book race is indistinguishable from one cooled for a changed plan; only one path
  emits an event.
- N10 — `funding_rate` unit differs per venue (8h vs 1h) under one name.
- N11 — `open_orders` completeness differs per venue under one name; `cancel_all` trusts
  the weaker one.
- N12 — position-lookup is implemented three times plus two inline copies with a different
  fallback in a fourth place.
- N13 — spot re-churn misclassification (INFER): "was an entry" keys on `not reduce_only`,
  true of *every* spot order — a voluntarily-cancelled spot exit gets the cooldown the
  comment says exits are exempt from; same bug class the side-vs-flag fix addressed.
- N14 — grid-flat behaviour vs docs: README and BOTS.md both promise a "position → 0 → bot
  kills itself" path that does not exist for grids; a flat grid re-plans a full entry
  ladder, which is correct and undocumented.
- N15 — `stop: adopt` reads only the stop-loss; README claims TP too.
- N16 — spot-borrow is four names across two concepts (`spot_borrow`, `is_leverage`,
  `isLeverage`, `spot_leverage`).
- N17 — three names for the notifier (`notify`, `notifier`, `Notifier`); "kind" renamed to
  "strategy" in prose only (three docstrings, zero code).
- N18 — errors.KINDS over-promises: Bybit can never emit `post_only_reject`; HL can never
  emit `tp_through_market`, `not_modified`, `cannot_modify`.
- N19 — `min_notional` is four upstream identities (linear key, spot key, HL constant,
  inverse None); HL's `min_qty` *is* its `qty_step` — one number, two names.
- N20 — the watchdog's `peak_equity(prev, None)` returns `prev or 0.0`; a falsy sentinel
  quietly disables the drawdown check on a fresh state file.
- N21 — `exit_markup_pct: 0` is explicitly accepted by the validator and silently floored
  back to 0.001 by the planner; the sibling keys' docs say "0 disables it". An off switch
  that isn't.
- N22 — dead-in-practice surface: `arm_order`, `exit_against`, the entire deadband family,
  and the entire `stop` subsystem are set by **zero** shipped fleet rows;
  `geometric_weights()` is exported and documented but called by no engine code;
  `trailed_bounds`' `deadband` parameter is always 0.0. The features most in need of
  renaming are also the least exercised — rename them before anything relies on them.
- N23 — the README-coverage spec checks only that each accepted key is *mentioned* in the
  README, never that the documented value validates — which is how every headline JSON
  example in the README came to be refused by the validator it documents (grid: `geo`/
  `flat`; martingale: `investment`; trail: all three key names; `exit_against: cell`;
  `arm_order: near/far`).

## 13. Open decisions for the migration map

1. `investment`/`capital` — **resolved in code** (capital + written-back notional), but
   GRID-MATHS teaches the opposite; the doc pass is unfinished (audit §2c).
2. Position ceiling name (`max_position` vs `max_position_base`) — audit §2d, still open;
   this file uses the unit-suffixed form throughout on the audit's own recommendation.
3. The lot's anchor (N2): ref-priced always, exit-priced always, or state-dependent as
   today — must be one, named, and specced.
4. `stop` → `watch` restructure (§7): rename the enum, or restructure the key. The
   restructure is strictly clearer; the rename is smaller.
5. Whether martingale keeps its own vocabulary (`levels`, `level_weights`) or adopts the
   grid's (`rungs`, `rung_weights`) — audit §2e proposed sharing; N3's side-conditional
   index reversal must be resolved *before* the names merge, or the merge will hide it.
6. One word each for the three hysteresis mechanisms and the two deadbands, none of them
   "hysteresis" or "deadband" unqualified.
7. One admissible-interval convention for fraction-valued keys, one exception type for
   config refusal, and a decision on whether nested objects (`trail`, `stop`) get the same
   unknown-key refusal as rows — v3 should have no second-class config.
8. `lower`'s martingale meaning needs its own name (`ladder_end`? `far_price`?) — one key
   whose meaning flips with strategy is the worst kind of pun.
9. Whether the martingale gains the grid's missing keys (position floor/ceiling, churn
   damping) or v3 documents their absence as intent.
