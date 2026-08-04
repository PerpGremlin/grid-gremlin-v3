# grid-gremlin v3

A grid and martingale execution engine for Bybit and Hyperliquid, built
vocabulary-first: one set of names shared by code, config, docs, and tests. Everything
below is pinned by the spec suite (`docs/SPEC.md`, IDs cited like `G7`); if this page
and the code ever disagree, a spec is failing somewhere and the code is right.

**Status: feature-complete, demo/testnet phase. There is no mainnet path in this
codebase — not a flag, an absence.**

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
BYBIT_DEMO=true            # demo | testnet | (mainnet refused)
HL_ACCOUNT_ADDRESS=0x...   # the wallet whose account is read
HL_TESTNET=true            # mainnet is unconstructible this phase
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
`--snapshot PATH`, `--snapshot-every N` (cycles, default 60). Ctrl+C leaves orders
resting — that is the feature, not a bug (see §5).

## 2. The fleet file

A JSON object (or a bare list of rows, treated as `{"bots": [...]}`):

```json
{
  "watchdog": "configs/watchdog.demo.json",
  "poll_seconds": 5,
  "notify_orders": false,
  "cancel_orders_on_exit": false,
  "bots": [ { ...rows... } ]
}
```

`watchdog` is **required** — nothing trades unwatched (F1). Unknown keys are refused
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
| `market_type` | `linear` / `inverse` / `spot` — picks the contract maths |
| `side` | `long` / `short` (spot cannot short) |
| `capital` | quote margin you commit; exposure = capital × leverage, derived and printed — never set `notional` yourself |
| `leverage` | 1–125, validated; also asserted on the venue at build |
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

The round's only exit is a whole-position take-profit at `take_profit_avg_pct` above
**average entry**, held on the venue and re-set as fills deepen (M4). A round is never
without an exit (M3): a target the market already ran through closes at
target-or-better. `repeat: true` re-anchors a new round at market — from flat only
(M5). Restarts adopt the resting TP and never rewrite a live round (M6).

Martingale is **Bybit linear only** this phase (HL cannot host the venue-side TP).

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
other than the grid's own exits gets the same treatment (S7). Every kill event states
what still rests on the venue (X4).

`server_side: true` (Bybit derivatives only): the venue hosts the stop, partial-sized
to the grid's inventory, following the position as it grows — it survives the process
dying. The strongest option; use it when the venue allows.

## 7. Venues and tiers

| | Bybit | Hyperliquid |
|---|---|---|
| tiers | demo (default) / testnet; **mainnet refused** | testnet only; **mainnet unconstructible** |
| markets | linear, inverse, spot | linear perps |
| wallet | unified account read | unified/spot-aware read (faucet USDC counted correctly) |
| stops | all watches; `server_side` on derivatives | `mark_price`/`account_equity`; `position_sl` inert; no `server_side` |
| martingale | linear only | not this phase |
| orders | post-only limits, everything | same (Alo), signed EIP-712, agent key |

Every order the engine places is post-only (G13's venue backstop): a crossing order is
rejected by the exchange, never taker-filled. HL testnet funds come from the faucet at
`app.hyperliquid-testnet.xyz` (~1,000 mock USDC, rationed — size like it's real).

## 8. Events

`[ship]` events reach Telegram (when keys are set): `fleet start seed fill exit tp
repeat funding margin backoff warn kill`. `[log]` events stay in the terminal:
`placed cancel amend skip` — order mechanics never page a human. Everything prints
locally either way; the terminal is the audit trail.

## 9. Development

- `python3 tests/run.py` — a spec is a `spec_*` function in `tests/spec_*.py`; its
  name carries the SPEC ID it pins (`spec_G7_...`). An error is a failure, never a
  skip. Every invariant has a spec; guards have *sabotage* specs proving the old
  incident returns when the guard is removed.
- One slice = one PR; `docs/PLAN.md` checkboxes update in the same PR as the work.
- Renames follow the `capital` pattern: old key refused with the migration stated,
  the whole seam changes in one commit (C2).

## The deeper story

| read | to learn |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | every invariant, by stable ID |
| [docs/JOURNAL.md](docs/JOURNAL.md) | the build, session by session |
| [docs/DECISIONS.md](docs/DECISIONS.md) | the owner's twenty decisions |
| [docs/MIGRATION.md](docs/MIGRATION.md) | every v2 name → its v3 fate |
| [docs/CONCEPTS.md](docs/CONCEPTS.md) | the dissection of v2 that started it all |
| [docs/PLAN.md](docs/PLAN.md) | the sixteen build slices, all ticked |
| [docs/BACKLOG.md](docs/BACKLOG.md) | what is not built yet, and why |
| [docs/research/](docs/research/) | the evidence trail |

*This repo is public and deliberately carries no account figures, no live position
data, and no deployment identifiers.*
