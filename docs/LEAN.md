# The lean copy and the field

**Status: study, 2026-08-03.** Three questions the owner asked: what features does v2
actually have; how simple could a copy be; and what do the commercial bots (Bybit, Pionex,
Binance, OKX, Bitget, KuCoin, Gate, 3Commas) do at each stage. Sources: the v2 dissection
(`CONCEPTS.md`) and two web-research passes over official help centers (URLs in the
research notes; where a vendor's help pages blocked fetching, details come from
search-indexed excerpts of the same official pages and are flagged).

This study updates one recommendation in `ALIGNMENT.md` §2 — see §4b below.

---

## 1. What v2 has — the honest inventory

**The core, used by every bot every cycle:** truth poll (the exchange is the state) ·
`plan()` (pure: config + truth → ideal ladder) · window (place near price, never cancel by
distance) · diff/apply (keep matches, amend qty-only changes, cancel before create) ·
order identity (`{botid}-{rung}-{gen}` — ownership, restart adoption, manual-order safety
from one string) · config validation (unknown keys refused) · fleet loop · events →
Telegram.

**Guards earned by live incidents (each has a date and a measurement):** cross guard ·
one-lot-per-rung on the exit side (the truncation churn: backoffs 88/hr → 0) ·
one-lot-per-rung on the entry side (rung 1838: 0 → 2.18 short in 12h) · split hysteresis
(ladder rewrites on sub-cent crossings) · flap cooldown · margin backoff (halts growth,
never the bot) · paginated truth ("a partial read is worse than a failed one") ·
truncation-tolerant diff.

**The adoption family, used live by the spot stacks and the HL positions:**
`min_position_base` (the floor that makes tight ranges over a stack possible) ·
`max_position_base` · `assumed_avg_entry` (spot-only basis fallback) · entry suppression
from held lots.

**Carried but set by zero shipped configs:** the entire `stop` subsystem · `trail` (one
historical test config) · `no_trade_pct` and both legacy deadband keys · the deadband
ratchet (~60 of the trickiest lines in bot.py, guarding knobs nobody turns) ·
`exit_against` · `arm_order` · the websocket wake · the backtester (dead at HEAD anyway) ·
`RECHURN_COOLDOWN` (already sentenced by the audit). The martingale runs on demo only.

## 2. How lean could a copy be

Engine today: ~2,900 lines plus ~950 of scripts, two venues. A faithful lean copy — **one
venue, grid only, core + earned guards + floor/cap adoption** — is roughly **1,400–1,600
lines**, about half, with nothing that live money actually uses removed. Cuts by size:
the Hyperliquid package (~1,500 lines, a third of it hand-rolled signing), martingale +
round lifecycle, deadband knobs + ratchet (keep only the hardcoded 0.1% fee floor — that
is part of the split, not a knob), trail, stops, WS wake, backtester.

Two cautions:

1. **The venue cut has teeth.** Dropping HL is the biggest simplification, but mainnet
   lives there; dropping Bybit keeps live money but loses demo, spot, and the safe test
   tier. And a "Bybit USDT-linear only" build re-creates what Pionex gives away free —
   BOTS.md §0's reason for this bot existing is inverse/USDC/hedge/fleet. So: one venue at
   launch, but **keep the adapter seam** (~200 lines) — the seam is cheap, the second
   venue is a slice, not a fork. (One honesty note: §0's claim that "nobody ships a bot
   for those" is now partially stale — Pionex ships a Coin-M futures grid. The hedge
   both-sides, fleet-scale, and adoption arguments still stand; see §4e.)
2. **Unused ≠ worthless everywhere.** v2's stops are unused *and* mis-designed (they die
   with the process); delete them in the copy and design the server-side stop fresh as a
   v3 requirement.

The lean copy is, deliberately, the same thing as the v3 walking skeleton: build it beside
v2, diff `plan()` against v2 on identical inputs, then add slices.

## 3. What the commercial bots do

### 3a. Grid lifecycle

| stage | Bybit spot | Bybit futures | Pionex | Binance spot | OKX futures |
|---|---|---|---|---|---|
| **start / seed** | market-buys base = per-grid qty × rungs above price; can fail on slippage | long/short: opens position at market on creation (size formula undocumented); neutral: no position | market-buys "portions" for rungs above price | same, plus an auto-refilled base-currency fee reserve | same, **but "Open Position on Creation" is a toggle, on by default** — the only opt-out seed in the field |
| **fund with held coins** | "In Base Token" | — | "Both" | dual-asset | quote/base/both; funds isolated |
| **sizing** | equal **base qty** per grid | f(investment, leverage) | equal **quote value** per grid (secondary source) | equal | equal |
| **per-grid profit** | buy at N → sell at N+1; "Grid Profit" vs "Total P&L" split everywhere | same | same | same, fees pre-deducted | same, plus funding fees folded into "Unpaired PnL" (unique) |
| **price leaves range** | **suspends, resumes** — never stops | positions stay open, idles with leveraged exposure | suspended, resumes | suspended, resumes | idles |
| **stop/termination** | settlement-asset choice = selling the seed optional | **always closes position** (only one) | sell-or-keep choice at close | sell-on-stop is an opt-in checkbox at creation | close-all or keep-positions choice |
| **trailing** | up only, shifts range one interval | up and down | infinity grid: constant-position-value invariant, no upper bound, no SL | — | up and down; edits re-initialize |
| **editable while running** | unclear | investment + TP/SL only | undocumented | stop-trigger prices only | broadly, but re-initializes |

### 3b. Martingale / DCA

Futures martingale products exist at **Bybit (futures-only), Bitget, KuCoin, OKX, Gate,
3Commas**; **Pionex and Binance are spot-only** (absences verified). No vendor documents
hedge mode or reduce-only TP. Only **Bybit displays the liquidation price on the bot
details page** — the best liq-vs-ladder presentation in the field.

The genre's sizing convention is **unambiguous: each order = k × the previous order**, a
geometric progression via a user multiplier — documented in those exact terms by all
seven multi-order products. The *only* budget-normalised presentation is Pionex's
Simple/AI mode (shares `1,1,2,4,8,16,32` — itself a doubling ladder expressed as weights).
Binance closes the loop by publishing the conversion: *total required = base + SO ×
Σ multiplierⁱ*. Hard multiplier caps of **2** exist exactly where the exchange holds the
user's perp margin (Bybit, Gate).

Other conventions worth knowing: base order and first safety order are sized
independently (3Commas/OKX/Bitget/Binance); a second **step-scale multiplier** compounds
the price gaps (3Commas invented it — 1%, 3%, 7%; OKX, Binance, Bitget copied; Bybit,
KuCoin, Gate use fixed steps); the step is measured from the **last fill** everywhere
except Bybit (average holding cost); TP is anchored to **average entry** everywhere
except Bybit (% of total investment); rounds auto-cycle everywhere except KuCoin
(undocumented); Bitget is alone in offering profit-compounding across rounds and an
"anchor next round to last round's average" trigger; 3Commas' "limit averaging orders
placed on exchange" is the field's only windowing analog — v2's window is ahead of
everyone else here.

## 4. What this teaches the open decisions

**a. Seed (ALIGNMENT §3b) now has prior art.** Every spot grid in the field seeds the
same way: market-buy exactly enough base to arm the rungs above the current price, at
creation. That is the same answer your spot-stack configs already encode ("the sellable
excess equals the rungs above spot") — the field just does it automatically. The design
that falls out: seed size = one lot per exit-side rung; market order; a failed or
slippage-broken seed **refuses to start** (Bybit documents this failure); a restart never
re-seeds because the position already exists (the venue is the state). OKX's opt-out
toggle is the right shape for config: seed on by default for a grid started mid-range,
`seed: false` to start entries-only.

**b. Martingale sizing (ALIGNMENT §2 ⚠ DECIDE) — recommendation updated.** The owner's
original definition ("each step a multiple of the previous order") **is the industry
convention**, in those words, across seven products — ALIGNMENT §2 recommended
normalised-weights partly on the grounds that multipliers were nonstandard; that ground
is gone. The budget-invariant argument still stands, but the field solves it without
weights: publish the required-capital series (Binance), cap the multiplier (Bybit/Gate at
2), cap the additions (KuCoin 1–25). Updated recommendation: **the config speaks
multiplier** (`size_multiplier`, `max_additions` — the genre's own vocabulary), **the
validator enforces the budget invariant** by expanding the geometric series and refusing
any ladder whose total exceeds `capital` — stated as a number in the error, the way
Binance states it as a formula. Weights survive only as the internal representation (and
a power-user override, which is Pionex DIY mode). This satisfies the trader's intuition,
the field's vocabulary, and the liquidation study's invariant at once.

**c. A new decision the field surfaced: TP basis.** v2's `take_profit_pct` is a fraction
of the **round's anchor**; the field's TP is a rebound from **average entry**, recomputed
as fills deepen (except Bybit's investment-ROI model). These differ exactly when it
matters — deep in a losing round, average is far from anchor, and an anchor-based target
is much further away than an average-based one. ⚠ DECIDE, and name the choice into the
key (`take_profit_from_anchor_pct` vs `take_profit_from_avg_pct`); the field's parameter
tables show what happens otherwise — eight products, five meanings of "take profit
ratio."

**d. Range-exit behaviour is settled by unanimity.** No commercial product converts
leaving the range into a stop — every one idles and resumes. v2's §5d idle is the field
consensus. The involuntary-flat question (ALIGNMENT §3's fifth state) remains v3's own to
answer — commercial bots don't face it because they own their TP/SL and close their own
positions.

**e. Where v2 is genuinely ahead of the field** — worth protecting in any lean cut:
adoption of an existing position (no commercial bot can — their only gesture is
fund-with-held-coins at creation); diff-based live-modify (the field's best is OKX, which
re-initializes on edit; Bybit futures allows investment and TP/SL only); hedge both-sides
on one symbol as two bots (undocumented everywhere); fleet-scale management; windowed
placement (only 3Commas has an analog). **Where the field is ahead:** the seed (universal,
v2 lacks it); required-capital display (Binance's formula, Bybit's liq-price-on-details);
auto-parameter modes (Pionex AI, Binance Auto, OKX presets — v3 non-goals, but know they
exist); and Bybit/Gate's multiplier caps as guardrails-by-default.
