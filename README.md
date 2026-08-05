# grid-gremlin v3

A grid and martingale execution engine for Bybit and Hyperliquid, built
vocabulary-first: one set of names shared by code, config, docs, and tests. Everything
below is pinned by the spec suite (`docs/SPEC.md`, IDs cited like `G7`); if this page
and the code ever disagree, a spec is failing somewhere and the code is right.

**Status: feature-complete, demo/testnet soak phase.** This software places real
orders on real venues. Read the Safety section before anything else.

---

## 1. Quickstart

Requirements: Python 3.11+, nothing else — the engine is stdlib-only by design
(including the Hyperliquid signing stack).

```bash
git clone https://github.com/PerpGremlin/grid-gremlin-v3 && cd grid-gremlin-v3
python3 tests/run.py                 # the whole spec suite; must be green
```

Create `.env` in the repo root (gitignored — a commit is a publication):

```
BYBIT_API_KEY=...          # demo-account keys
BYBIT_API_SECRET=...
BYBIT_DEMO=true            # demo | testnet | mainnet (double-gated, see Safety)
HL_ACCOUNT_ADDRESS=0x...   # the wallet whose account is read
HL_TESTNET=true            # testnet; mainnet is double-gated (see Safety)
HL_PRIVATE_KEY=0x...       # a TESTNET agent/API wallet key — never a main key
TELEGRAM_BOT_TOKEN=...     # optional: shipped events go to your phone
TELEGRAM_CHAT_ID=...
```

Sanity-check each venue read-only, then run a fleet:

```bash
python3 -m gridgremlin.exchange.bybit BTCUSDT linear   # live truth, schema-validated
python3 -m gridgremlin.exchange.hyperliquid BTC        # same, HL testnet

python3 -m gridgremlin configs/fleet.demo.json \
        --snapshot logs/snapshots-demo.jsonl           # runs until Ctrl+C
python3 -m gridgremlin.watchdog configs/watchdog.demo.json   # one-line verdict
```

CLI flags: `--cycles N` (finite run), `--interval S` (override poll),
`--snapshot PATH`, `--snapshot-every N` (cycles, default 60), `--allow-mainnet`
(half of the safety below). Ctrl+C leaves orders resting — that is the feature,
not a bug (see §5). The deploy doctrine is `--interval 1` (D22): the venue's own
rate budget is the real pace, so 1 means "as fast as the venue permits".

## Safety — the helmet and the armour

By default this engine can only reach **demo and testnet** venues: the env flags
(`BYBIT_DEMO=true`, `HL_TESTNET=true`) select paper venues — that is the helmet.
**Real funds are double-gated on top (F7/D25) — the armour.** Mainnet fires only
when BOTH of these are true, per launch:

1. the fleet file declares `"allow_mainnet": true` — committed, reviewed intent;
2. the command line passes `--allow-mainnet` — operator intent, every start.

Either alone refuses, naming the missing half. **No fleet file in this repository
carries the flag, ever** — cloning this repo cannot reach real money by accident,
and arming it is a deliberate two-step act. The promotion checklist (evidence
gate, key ceremony, cutover) is [docs/PROMOTION.md](docs/PROMOTION.md).

## 2. The fleet file

A JSON object (or a bare list of rows, treated as `{"bots": [...]}`):

```json
{
  "watchdog": "configs/watchdog.demo.json",
  "poll_seconds": 5,
  "notify_orders": false,
  "bots": [ { ...rows... } ]
}
```

`watchdog` is **required** — nothing trades unwatched (F1). Optional fleet keys:
`allow_mainnet` (half of the Safety gate, never set in this repo) ·
`tombstones` (path of the stop-fire tombstone file, default
`logs/tombstones.json` — see §6) ·
`preflight` — `{"probe": true, "max_failed_bots": 0}`: the probe places one
unfillable post-only rehearsal order per bot at build and cancels it, proving
the whole placement path before any strategy order; a failing bot refuses the
fleet at tolerance 0 (D7) or builds dead-and-visible within a higher tolerance
(F8/D27). Unknown keys are refused
everywhere, including inside nested objects; a misspelling gets a did-you-mean hint;
old v2 key names get their migration stated. **One bad row refuses the whole fleet**
(C6) — no silent skips. Keys starting `_` are comments.

## 3. Grid rows

```json
{ "venue": "bybit", "market_type": "linear", "symbol": "BTCUSDT", "side": "long",
  "capital": 300, "leverage": 10,
  "lower": 62000, "upper": 66000, "rungs": 41,
  "split_hysteresis_rungs": 0.3,
  "stop": {"watch": "mark_price", "level": 61500, "server_side": true} }
```

| key | meaning |
|---|---|
| `venue` | `bybit` (default) or `hyperliquid` |
| `market_type` | `linear` / `inverse` / `spot` — picks the contract maths. Inverse: qty is $1 contracts, PnL in the BASE coin (A4), margined in it too |
| `side` | `long` / `short` (a spot short only under `spot_borrow`, D24) |
| `capital` | quote margin you commit; exposure = capital × leverage, derived and printed — never set `notional` yourself |
| `leverage` | 1–125, validated; also asserted on the venue at build. **Spot refuses this key** — spot sizing is `spot_leverage` under borrow |
| `spot_borrow` / `spot_leverage` | spot only, together or refused (D24): every order carries the venue's borrow flag, sizing = capital × spot_leverage (1–10), and the position is the SIGNED wallet balance — negative is a short |
| `lower` / `upper` | the range. Rungs are computed once; **price never moves them** (G1) |
| `rungs` **or** `spacing_pct` | give exactly one; the other derives, and the stored spacing is the gap the lattice actually has (G2) |
| `spacing_type` | `percent` (geometric, default) / `fixed` (arithmetic) |
| `rung_sizing` / `rung_weights` | `equal` (default) or `weighted` + one positive weight per rung |
| `place_within_pct` | the placement window, default 0.05. **Limits placement, never cancellation** (W1) |
| `split_hysteresis_rungs` | 0–0.5 of the narrowest rung gap; holds the entry/exit split still through jitter. 0 ≡ unset (default) |
| `min_position_base` | the floor: never sold, not by exits, **not by a stop** (X6) |
| `max_position_base` | the cap, in base units; `"unbounded"` to lift; omitted = the full ladder |
| `assumed_avg_entry` | spot only: your cost basis fallback; venue truth always wins |
| `seed` | `true`: on a flat first start, market-buy one lot per exit-side rung so the ladder starts covered (D9). A restart never re-fires it — done-ness is read from the venue |
| `stop` | see §6 |

**What a grid does** (the five ideas, one line each): the exchange is the state — kill
the process any time, nothing is lost · it refuses, it does not adapt · one lot per
rung, and **an entry never re-arms until its exit has filled** (G7) · exits never rest
below cost + fees (G6) — adopted positions get a no-trade zone around the basis with
zero configuration (D6) · your edge is the range; out of range it idles and waits.

## 4. Martingale rows

```json
{ "strategy": "martingale", "venue": "bybit", "symbol": "SOLUSDT", "side": "long",
  "capital": 500, "leverage": 5,
  "base_order_size": 100, "safety_order_size": 100,
  "order_size_multiplier": 2, "deviation_pct": 0.005,
  "deviation_step_multiplier": 1, "max_averaging_orders": 2,
  "take_profit_avg_pct": 0.01, "repeat": false }
```

The 3Commas vocabulary (D11): the base order fills at market when the round opens;
each safety order is `order_size_multiplier` × the previous one, resting
`deviation_pct` steps below the base price with gaps compounding by
`deviation_step_multiplier`. No range bounds — depth derives from the schedule, and
the validator expands the whole series and **refuses a ladder the capital cannot
carry, stating the number** (M2).

The round's exit measures from **average entry**, re-anchored as fills deepen (M4),
and a round is never without one (M3) — a target the market already ran through
closes at target-or-better. Two shapes, pick ONE:

- `take_profit_avg_pct` — the whole position at one target;
- `take_profit_tranches` — shares of the position at ascending targets, e.g.
  `[{"at_avg_pct": 0.01, "share": 0.5}, {"at_avg_pct": 0.02, "share": 0.5}]`
  (shares must sum to 1). Hosted on Bybit's conditional book; on HL each tranche
  is its own resting reduce-only exit (M10).

Optional round machinery: `trailing_stop_pct` (the venue trails the position from
the average — Bybit only, refused elsewhere, M11) · `repeat: true` re-anchors a new
round at market, from flat only (M5) · `repeat_cooldown_seconds` waits that long
**from the venue's timestamp of the TP fill** before the next round (M13) ·
`reinvest: true` scales the next round's sizes by realized-net/capital over the
last 30 days of venue fills, floored at 0 and capped at +20% — the watchdog ceiling's own
headroom (M12); off, you compound by editing `capital`, which is also the only
path grids have. Restarts adopt the resting exits and never rewrite a live round
(M6).

Martingale runs on **both venues** (D21): Bybit hosts the position-TP natively;
HL gets a resting reduce-only limit at the target, adopted by identity.

## 5. Running, restarting, stopping the process

- **One fleet process per account** — enforced by a lock file, the second process
  refuses (F3).
- **Restarts are non-destructive**: resting orders are re-adopted by identity with
  zero churn; positions are read from the venue; a martingale round's TP is believed
  as found. What resets (and is safe to reset): churn-guard counters, the held split
  ref, the fill baseline. `--cancel`-style teardown does not exist; Ctrl+C leaves the
  book resting.
- At build the fleet prints its worst case: `projected full-deployment: MM x% / IM y%
  of equity`. The number you see is the number you typed.
- Snapshots (`--snapshot`) append one JSONL row per interval — equity, mm_rate, every
  bot **including dead ones** (F4). The watchdog reads the last row and pages on:
  no/stale snapshot, mm_rate, equity floor, drawdown from peak, per-bot position
  bounds, missing bots. Its config requires `assumes_sole_actor` — say out loud
  whether a human also trades this account (F6).

## 6. Stops — the off button

```json
"stop": {"watch": "mark_price", "level": 61500, "server_side": true}
```

- `watch: mark_price` — fires when mark crosses `level` on the losing side.
- `watch: account_equity` — fires when whole-account equity ≤ `level` (absolute, ≥ 1).
- `watch: position_sl` — no level: the bot reads the stop-loss **you** placed on the
  venue position and honours it. (Inert on HL — the venue has no position SL field.)

Firing means: **flatten the grid's inventory at market, cancel every owned order,
kill, never restart** (D1). The `min_position_base` floor **survives** — a stop closes
what the grid built, not your stack (X6/D2). A position that goes flat by any hand
other than the grid's own exits gets the same treatment (S7) — with one stated
exception: a repeat martingale on Bybit cannot tell your manual close from its
own hosted TP filling (both look identical in truth) and will open a new round;
the watchdog's `assumes_sole_actor` is that assumption made explicit (M5a). Every kill event states
what still rests on the venue (X4).

`server_side: true` (Bybit derivatives only, and only with `watch: mark_price`):
the venue hosts the stop, partial-sized to the grid's inventory, following the
position as it grows — it survives the process dying. The strongest option; use it
when the venue allows.

**After a stop fires — the tombstone (X7).** The botid is written to
`logs/tombstones.json` BEFORE the flatten, so a stopped bot stays stopped through
any restart or crash: at build it comes up dead-and-visible, warning with its
reason. Revival is deliberate: delete its entry from the file, then restart. There
is no automatic path back — that is the point.

## 7. Venues and tiers

| | Bybit | Hyperliquid |
|---|---|---|
| tiers | demo (default) / testnet / mainnet | testnet / mainnet |
| mainnet | **double-gated** (see Safety): fleet `allow_mainnet` AND `--allow-mainnet` | same double gate |
| markets | linear, inverse, spot | linear perps |
| wallet | unified account read | unified/spot-aware read (faucet USDC counted correctly) |
| stops | all watches; `server_side` on derivatives | `mark_price`/`account_equity`; `position_sl` inert; no `server_side` |
| martingale | linear (native position-TP) | linear (resting reduce-only exit, D21) |
| orders | post-only limits, everything | same (Alo), signed EIP-712, agent key |

Every order the engine places is post-only (G13's venue backstop): a crossing order is
rejected by the exchange, never taker-filled. HL testnet funds come from the faucet at
`app.hyperliquid-testnet.xyz` (~1,000 mock USDC, rationed — size like it's real).

## 8. Events

`[ship]` events reach Telegram (when keys are set): `fleet start seed fill exit tp
repeat funding margin backoff warn kill`. `[log]` events stay in the terminal:
`placed cancel amend skip` (order mechanics) and `net` (network weather — lost
cycles and their recoveries; the loop absorbs them and the phone never hears
about them). Everything prints locally either way; the terminal is the audit
trail.

## 9. Reading the results

```
python3 -m gridgremlin.report configs/fleet.demo.json --hours 24
```

Pulls fill history from the venue (never a local guess — R1), attributes each
fill to its bot by order link, and prints per bot: **realized** (matched
profit, average-cost), **fees**, the open remainder at its average cost,
**unreal** (mark-to-average), and **total**. *Grid profit = realized − fees*
(D8). Fills no bot owns — manual trades, or engine market orders placed before
market-order identity landed (I5) — appear in an `unowned` bucket per symbol
rather than disappearing (R3). Read-only: safe to run any time,
anywhere, alongside a live fleet (R4). A venue that cannot be reached is
skipped with a warning; unknown marks print `—`, never a guess (R5).

## 10. Backtesting

```
python3 -m gridgremlin.backtest_cli configs/fleet.demo.json --bot linSOLUSDTl \
        --days 7 [--bar-minutes 60] [--fee 0.0002] [--funding 0]
```

Fetches real venue klines (public data, no keys) and replays the SAME `plan_grid`
the live engine runs (T3) — fills require trade-through, never touch. Bybit grids
only; HL bots and martingales are refused by name. Prints grid profit, fees,
funding, max drawdown, trips, and what the run ends holding.

## 11. Development

- `python3 tests/run.py` — a spec is a `spec_*` function in `tests/spec_*.py`; its
  name carries the SPEC ID it pins (`spec_G7_...`). An error is a failure, never a
  skip. Every invariant has a spec; guards have *sabotage* specs proving the old
  incident returns when the guard is removed.
- One slice = one PR; `docs/PLAN.md` checkboxes update in the same PR as the work.
- Renames follow the `capital` pattern: old key refused with the migration stated,
  the whole seam changes in one commit (C2).

## 12. Working with an agent (recommended)

This system is built and operated the way it reads: a human making every
decision that matters, an AI agent doing the building, testing, and watching at
machine speed. The decisions file is the human's voice; the spec suite is what
keeps the agent honest. It is a genuinely better division of labour than either
party alone, and this repo is set up so you can reproduce it.

The full shape uses a workstation plus a VPS: the fleet runs unattended on the
box (`ops/` — units, watchdog, alerts), the box carries its own read-only agent
layer (triage on failure, the Telegram relay, the daily range review), and a
workstation agent session does the hands-on work — config edits, PRs, deploys,
investigation — with the human deciding and merging.

**No VPS? Start with one agent in one terminal.** Run the fleet in one shell,
and an agentic CLI (this repo was built with Claude Code) in a second, opened
at the repo root. Even read-only it will earn its keep: ask it to validate and
explain a fleet file before you run it, read the readout and the logs, explain
any warn verbatim, or run a backtest on your proposed grid. Give it guardrails
the way this repo gives its own agents guardrails: `ops/triage-settings.json`
is a ready-made read-only cage (`claude --settings ops/triage-settings.json`),
the suite must be green before anything merges, and the mainnet double-safety
(see Safety) is never the agent's to arm. The one rule that transfers above
all: the agent proposes and builds — the human decides, and reads everything.

## The deeper story

| read | to learn |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | every invariant, by stable ID |
| [docs/JOURNAL.md](docs/JOURNAL.md) | the build, session by session |
| [docs/DECISIONS.md](docs/DECISIONS.md) | the owner's twenty decisions |
| [docs/MIGRATION.md](docs/MIGRATION.md) | every v2 name → its v3 fate |
| [docs/CONCEPTS.md](docs/CONCEPTS.md) | the dissection of v2 that started it all |
| [docs/PLAN.md](docs/PLAN.md) | every build slice, phases 1 and 2 |
| [docs/PROMOTION.md](docs/PROMOTION.md) | how v3 reaches real funds — the checklist |
| [ops/README.md](ops/README.md) | the deploy layer: units, alerts, triage, relay, range review |
| [docs/BACKLOG.md](docs/BACKLOG.md) | what is not built yet, and why |
| [docs/SOAK.md](docs/SOAK.md) | the experiment registry and its call conditions |
| [docs/research/](docs/research/) | the evidence trail |

*This repo is public and deliberately carries no account figures, no live position
data, and no deployment identifiers.*
