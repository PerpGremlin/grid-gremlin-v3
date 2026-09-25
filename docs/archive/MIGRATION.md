# Migration map — v2 → v3, frozen

**Status: frozen 2026-08-04. Nothing here is relitigated mid-pass** (the method, step 2).
Every v2 name gets exactly one fate. Authorities: the audit's §2 draft (adopted), the
concept inventory (`CONCEPTS.md`), and the decision record (`DECISIONS.md`, D-numbers).
Where a final v3 spelling is still open it is marked *(spelling at slice N)* — the fate
is frozen, the letters aren't.

**Execution rule — the `capital` pattern, this time completely (C2):** every RENAME,
RESTRUCTURE and RETIRE below goes into the refusal table with a migration message; the
old key is *refused*, never aliased; readers, validator, docs, examples and error text
change in the same commit; a spec pins both sides. v2's lesson: its rename covered one
key of twenty-one and left five live defects — the refusal table below **is** the
checklist, all of it.

Fates: **KEEP** (name and meaning survive) · **RENAME** · **RESTRUCTURE** (shape
changes) · **RETIRE** (concept leaves v3) · **NEW** (no v2 ancestor) · **DEFER** (not in
the skeleton; listed so it isn't reinvented).

---

## 1. Config keys — common

| v2 | fate | v3 | authority |
|---|---|---|---|
| `venue` | KEEP | `venue` — but validated (values, at config level) | C1 |
| `category` | RENAME | `market_type` (`linear`/`inverse`/`spot`), validated | audit §2a |
| `symbol` | KEEP | `symbol` | audit §2f |
| `side` | KEEP | `side` (`long`/`short`) | audit §2f |
| `strategy` | KEEP | `strategy` (`grid`/`martingale`), normalised back for both | audit §2a; config M14 |
| `capital` | KEEP | `capital` (quote; margin committed) — `investment` stays refused | audit §2c, done in v2 |
| `notional` (as input) | RETIRE | refused as input; internal derived `ladder_notional` | D8; C4; config M6 |
| `leverage` | KEEP | `leverage` — **now validated** (type, sign, range) | config M3 |
| `stop` | RESTRUCTURE | `stop: {watch: mark_price \| account_equity \| position_sl, level, …}` + server-side opt-in key; semantics = flatten grid inventory, kill, no restart *(final sub-keys at slice 13)* | D1–D3; X1–X6 |
| `stop.type: price/equity/adopt` | RESTRUCTURE | → `watch: mark_price / account_equity / position_sl` | D3; CONCEPTS §7 |
| `stop.value` | RENAME | `stop.level` *(spelling at slice 13)* | X2 |

## 2. Config keys — grid

| v2 | fate | v3 | authority |
|---|---|---|---|
| `upper` / `lower` | KEEP | grid range bounds | audit §2f |
| `rungs` | KEEP | rung count; XOR with spacing, pair reconciled | G2 |
| `spacing_pct` | KEEP | fraction under `percent`, price under `fixed` | audit §2a |
| `spacing_type` | KEEP | `percent`/`fixed` | audit §2a |
| `rung_sizing` | KEEP | `equal`/`weighted` | audit §2a |
| `rung_weights` | KEEP | with `weighted` | audit §2a |
| `place_within_pct` | KEEP | the placement window | audit §2a; W1 |
| `split_deadband_rungs` | RENAME | `split_hysteresis_rungs` — "deadband" appears nowhere unqualified | B1, B2 |
| `no_trade_pct` | RETIRE | emergent (D6): the suppression needs no key | D6; B9 |
| `entry_deadband_pct` | RETIRE |〃 | D6 |
| `exit_deadband_pct` | RETIRE | 〃 (was bot-written anyway) | D6; config E4 |
| `exit_markup_pct` | RETIRE | the 0.1% floor is the internal constant `FEE_FLOOR_PCT` | D6; G6 |
| `exit_against` | RETIRE | the exit floor is unconditional — no `rung` bypass | G6; N22 (set by nothing) |
| `arm_order` | RETIRE | nearest-first only in the skeleton; furthest-first returns only with a spec and a user | N22; audit 3.4 |
| `assumed_avg_entry` | KEEP | spot-only basis fallback; venue always wins | audit §2a; S4 |
| `min_position_base` | KEEP | the floor; unit stays in the name | D16; G9 |
| `max_position_base` | KEEP | the cap; unit stays in the name | D16; G9–G10 |
| `spot_borrow` / `spot_leverage` | KEEP | spot only; borrow flag + account leverage | audit §2a |
| `trail` (+ `sma_periods`, `trail_min`, `trail_max`) | RETIRE | range edits through the diff; no SMA machinery | D10 |
| — | NEW | `seed` (bool): flat-start market seed covering the exit side | D9; S3 |

## 3. Config keys — martingale (the 3Commas restructure, D11/D13)

| v2 | fate | v3 | authority |
|---|---|---|---|
| `levels` | RESTRUCTURE | → `max_averaging_orders` (count of safety orders; base order separate — note the off-by-one vs v2's total-levels) | D11 |
| `level_weights` | RETIRE | → `order_size_multiplier` (each safety order = k × previous); per-order overrides DEFER (DIY mode) | D11; D17 |
| `first_entry` | RESTRUCTURE | → the base order (price/market at start) *(spelling at slice 5)* | D11 |
| `lower` (martingale) | RETIRE | depth derives from deviation schedule × max orders | D13; M8 |
| `spacing_type` (martingale) | RETIRE | → `deviation_pct` + `deviation_step_multiplier` | D11 |
| `take_profit_pct` | RENAME | basis becomes average entry, named into the key *(spelling at slice 12)* | D12; M4 |
| `take_profit_price` | RETIRE | dead in v2 (N0e); absolute TP leaves entirely | D11; M5 |
| `repeat` | KEEP | round looping; refused with nothing now (absolute TP gone) | M5 |
| — | NEW | `base_order_size`, `safety_order_size`, `deviation_pct`, `deviation_step_multiplier` | D11 |
| — | DEFER | signal start-conditions only (owner does their own TA); partials/trailing built via D23, reinvest/cooldown via D26 | D15; D23; D26 |

## 4. Fleet, watchdog, CLI

| v2 | fate | v3 | authority |
|---|---|---|---|
| `bots`, `poll_seconds`, `cancel_orders_on_exit`, `notify_orders` | KEEP | fleet keys — `poll_seconds` now type-validated; bare-list files get the same key check | config K2, M15 |
| row-skip on bad row | RETIRE | a bad row refuses the whole fleet | D7; C6 |
| watchdog keys (`tag`, `snapshot`, `state`, `staleness_seconds`, `mm_rate_max`, `equity_min`, `equity_drawdown_max`, `re_alert_seconds`, `positions`, `suppress_when_failed`) | KEEP | all — but they gain a validator (v2 had none); `equity_min` documented as the same quantity as `stop.watch: account_equity`'s level | F1–F6; audit 3.6 |
| `--allow-mainnet`, `--dry-run`, `--cycles`, `--interval`, `--cleanup`, `--snapshot*` | KEEP | CLI surface; `--kline`/`--bars`/`--fee`/`--no-funding` return with the rebuilt backtester (slice 15) | F5 |
| `--wake` / WS wake | DEFER | poll is truth; the latency hint returns only if wanted after the skeleton | LEAN §2 |

## 5. Internal vocabulary (the code's names)

| v2 | fate | v3 | authority |
|---|---|---|---|
| `ref` / `truth['ref']` | RENAME | `split_ref` — the tradeable split reference | CONCEPTS §3 |
| `_sticky_ref` (+ a local named `mark` holding a ref) | RENAME | `held_split_ref`, the hysteresis value; `window()`'s parameter names the ref it receives | B2; W2; N4 |
| `lot` | KEEP | ref-priced always | D5; G4 |
| `held` vs `total` | RENAME | `held_base` vs `sellable_base` — never one variable | G9; the overnight cap failure |
| `n_held` | RENAME | `lots_held`; `lots_free` KEEP | CONCEPTS §1 |
| `EXIT_MARKUP_PCT` | RENAME | `FEE_FLOOR_PCT` | G6 |
| `CROSS_GUARD_BPS` | KEEP | one definition, one implementation, venue-neutral home | B3; N6; M35 |
| `RECHURN_COOLDOWN` | RETIRE | flap cooldown survives, per-cause (B6); the boundary is the hysteresis's job | audit 3.5 |
| `_kill` / `cancel_all` | RESTRUCTURE | one flatten-and-kill path, paginated truth, owned orders only | X1, X5; N1 |
| "adopt" (the word) | RESTRUCTURE | four concepts, four names: `watch: position_sl` (stop) · re-adoption by identity (restart orders) · TP adoption (martingale round) · the **adopt** start state (positions) — the word alone means only the last | CONCEPTS §6.5 |
| `kind` (strategy local) | RENAME | `strategy` everywhere (docstrings included) | exchange M5 |
| `cell` (local), `first_entry` tag in dry-run | RETIRE | die with `exit_against` / the martingale restructure | G6; D11 |
| event vocabulary (17 kinds) | KEEP | minus `trail`; `kill` now means flatten-and-kill; event text states on-venue residue | D1; X4 |
| error kinds | KEEP | per-venue emit-ability documented (no over-promising union) | N18 |
| `truth` dict shapes | RESTRUCTURE | one validated schema; units carried; three position shapes become one | V1–V3 |

## 6. Modules

| v2 | fate | v3 |
|---|---|---|
| `strategy/grid.py` + `strategy/martingale.py` | RESTRUCTURE | one ladder module; martingale = data over it (M1) |
| `window.py` | KEEP | still ~a dozen lines, honest parameter name |
| `apply.py` + `bot.py`'s `_apply` | KEEP | the diff/apply seam, truncation-tolerant |
| `trail.py` | RETIRE | D10 |
| `stops.py` | RESTRUCTURE | flatten-and-kill + watch + server-side key (slice 13) |
| `wake.py` / `wsclient.py` | DEFER | poll is truth |
| `backtest.py` | RESTRUCTURE | rebuilt at slice 15: trade-through fills, funding, v2-diff harness |
| `exchange/bybit/*` | KEEP | first venue (D19), behind the adapter seam |
| `exchange/hyperliquid/*` | DEFER | slice 16 |
| `scripts/watchdog.py`, `relay.py` | KEEP | ops layer; watchdog config gains a validator |
| `scripts/flap_report.py`, `portfolio_view.py` | DEFER | diagnostics return as needed |

---

*Count check: 21 grid/common keys, 9 martingale keys, 10 watchdog keys, 6 CLI flags, 16
internal names, 12 modules — every name in the concept inventory has a row here or is
covered by its section's KEEP. If a v2 name surfaces during the build without a row, the
build stops and the row is added first.*
