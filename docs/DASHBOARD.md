# The dashboard — design notes

Research and decisions for a companion project: a panel that lets a person
configure, start, watch and stop this engine without writing code or using an
agent. **Not built yet.** This file exists so the vocabulary is settled before
any of it is, which is the same rule the engine was built under.

Researched 2026-08-06 by three independent reviewers: what the commercial
products do and what users complain about, and what form factors are possible
for a stdlib-only engine. Sources are cited in the research; the conclusions
are here.

## 1. The finding that matters

Almost every complaint about Pionex, 3Commas, Bybit, Binance and KuCoin bot
dashboards is a **naming failure, not an engine failure.** The v2 audit's
thesis, independently reproduced across five commercial products. Five shapes,
each with a twin in this repo's own dissection:

1. **One word, two quantities.** "Profit" means closed-only on one screen and
   including-floating on another. Pionex ships two different things both called
   *close bot*; its support answers contradict each other as a result. 3Commas
   shows two profit numbers under one label — asked which to trust, the
   community answer was *"you get to choose which one you like better."*
2. **A verb that doesn't do what it says.** 3Commas: *"Take Profit for DCA bot
   doesn't mean 'close at market price'. Take profit means 'start trailing'."*
   And: *"When you turn off a bot all existing deals that bot started remain
   running."*
3. **A name describing mechanism, not effect.** "Step scale", "volume scale" —
   no unit, no consequence, so every support thread ends in hand-arithmetic.
4. **A dominant state with no name.** Out-of-range / fully-bought /
   ladder-exhausted. Users invented the word **"stuck"** and it has been the
   top support question for five years. This is the direct analogue of v2's
   `stop: {type: "adopt"}` — a real state nobody could name, so nobody
   understood it.
5. **A headline that structurally excludes the loss and only rises.** Pionex's
   own docs say grid profit *"never decreases"*. Then it gets annualised:
   Binance's documented formula divides by runtime **in minutes**; Bybit counts
   a bot that ran under a day as having run one day.

The consequence, in users' own words, is the same story over and over: the
screen said they were up, the settlement said otherwise, and the word *scam*
appears within a message. The most-cited near-miss: a user stops a bot showing
**50% grid profit** and lands exactly at break-even.

**The cautionary tale.** 3Commas conceded this in April 2024 and shipped a
realised/unrealised split *retroactively*, warning users that *"the displayed
value could change in some places."* That is the retro-rename the `capital`
pattern (C2) exists to prevent — a product telling its users the number they
had been reading may have meant something else. Settle the vocabulary first.

### The best evidence is not from the commercial products

A fourth reviewer read the open-source engines (freqtrade, OctoBot, Jesse,
Nautilus, Hummingbot) at source rather than through their docs, and found this
repo's thesis in the wild:

**OctoBot renamed `ALLOW_WITHDRAWAL_KEYS` → `ALLOW_FUNDS_TRANSFER` and inverted
the default in the same change.** The old name still sits in a public archived
repository teaching the opposite behaviour. The reviewer's own assistant read
the archived copy and reported the safety default **backwards** — a rotted name
in a stale copy, believed, about a withdrawal permission on a live trading bot.
That is more useful evidence than anything in the v2 audit, because it is
someone else's failure, in public, with the artefact still there to point at,
and because the way it was discovered *is the failure mode itself*.

Two more, both from reading code rather than docs:

- **`safe_dump` is not atomic.** It truncates in place and protects itself with
  a `.back` sidecar and an exception handler — closing exactly one of the two
  windows. SIGKILL, OOM and power loss are all still open. "Safe" in a function
  name is a claim, and a claim needs a spec (T1).
- **No double-start guard.** A second OctoBot instance fails to bind its UI
  port, the UI thread logs and dies — **and the trading engine keeps running
  headless.** Two engines on one account, one of them invisible. The port was
  serving as an accidental mutex, and it failed open. This repo's F3 lock is
  the same idea done deliberately; the lesson is that the guard belongs in the
  *engine*, never in the UI.

## 2. Vocabulary rules (before any code)

- **Never the bare word "profit".** Four quantities, four names, always
  distinguishable: realised (matched), fees, unrealised (mark-to-average), and
  **settled** (what you would actually receive). The engine's readout already
  separates the first three; the dashboard must not re-merge them.
- **The unit belongs in the name** (D16's rule, extended). Every APR complaint
  in the research dissolves if the number is `grid_profit_quote_7d` rather than
  "APR".
- **The headline is total equity, not realised profit.** Every independent
  critic converges on this; it is the direct fix for the loudest complaint.
- **Every state has a name.** `IDLE (out of range, 3 rungs below)`,
  `HOLDING (ladder exhausted)`, `RETIRED (tombstoned: reason)`. Never a silent
  "Working" for a bot that is doing nothing — the failure that made users
  invent "stuck".
- **No extrapolation.** Show the window and the number in it. If someone wants
  it annualised, that is their arithmetic and their assumption.

## 3. Features, ranked by evidence

1. **Settlement preview** — *"if you stop this bot now you receive X quote and
   Y base, after estimated fees"*. This single panel answers the complaint that
   generates the word *scam*, and needs no write authority.
2. **Both denominations, always** — 12.4 LTC *and* 560 USDT. KuCoin's own FAQ
   carries the complaint verbatim: *"why do I get back less base currency after
   closing the bot?"*
3. **Distance to the range edges**, and the named idle state when outside.
   Requested directly by users; shipped by nobody.
4. **A hold benchmark** — what the same capital would have done just holding.
   Users ask for it in plain words across every platform; nobody ships it.
5. **Fee visibility** — fees paid as a share of realised, per bot. Grid trading
   is a fill-often machine and fees are the quiet drag; this repo has already
   measured a live case where they exceeded gross.
6. **Ladder progress** — safety orders used vs authorised (`3/10`), max depth
   reached. Requested; absent everywhere. Already computed here (R6).
7. **Dry-run before apply** — for a proposed config change, show which orders
   would be placed and cancelled. The most valuable thing a grid panel can do,
   and it needs zero write authority.

Deliberately **not** shipped: APR, an "AI parameters" button fitted to a week
of data, a win-rate that flatters by ignoring open positions.

## 4. Form

Default case: **one person, one machine** — engine, panel, keys and browser all
local. No SSH, no VPS. A remote box is a variant, not the design centre.

- **The panel is a small localhost HTTP server** rendered in the user's own
  browser. It is the only option that is bidirectional, and both control and
  key entry are write paths. Live data by polling; no websockets needed at a
  seconds-scale cadence.
- **A self-contained HTML exporter** shares the same renderer for the artefact
  case (end-of-session report, something to attach to a bug report).
- **An ANSI terminal view** as the no-browser fallback. Note `curses` is *not*
  stdlib on Windows and is therefore disqualified as the cross-platform answer.
- Charts are **server-side inline SVG**: a range is a rectangle, rungs are
  lines, an equity curve is a path. Styleable (so dark mode is free), tooltips
  via `<title>` with no JavaScript, diffable in review. Refuse pan and zoom —
  that is where the thousands of lines and the rot live.

## 5. Security floor (non-negotiable)

A panel bound to loopback is **not** private from the browser: any page the
user visits can attempt requests to it, and DNS rebinding defeats naive origin
checks. This is *more* dangerous locally than on a tunnelled server, because
the panel listens for the whole time the user is browsing, and it can stop
trading and holds keys.

- Bind `127.0.0.1` explicitly; random port; never all-interfaces.
- Allowlist the exact `Host` header (this alone defeats rebinding).
- Per-launch capability token in the URL, exchanged for a cookie and stripped
  from history on first load.
- Mutations: POST + a custom header + a synchroniser token; verify `Origin`;
  emit no CORS headers at all; cap body size.
- **Keys are write-only.** The panel shows *"a key is stored, added 2026-08-04,
  ends …7f3a"* and never re-serves the value. Then a total origin bypass steals
  nothing, because no response body anywhere contains a key.
- Keys live in the per-user config directory at `0600`, created with those
  permissions rather than chmod'ed after; refuse to load a group/other-readable
  secrets file and say why.

**And the control that dominates all of the above: refuse an over-privileged
key** — which is not a new idea, and the prior art carries its own lesson.
OctoBot already checks API key permissions at connection, on by default, and
forked ccxt to add the `fetchPermissions` upstream lacks. But when an exchange
does not support the check it **returns silently — fail-open**. Copy the check;
close that hole. An unverifiable key is not a permitted key (E8: unknown is not
flat). Bybit's `GET /v5/user/query-api`, authenticated with the key being
checked, returns its permission set, read-only flag, IP allowlist and expiry.
If it can withdraw, the panel refuses to start — not a warning banner, a
refusal — and it re-checks at *every* startup, because permissions can be
widened later on the exchange's website. For Hyperliquid, require an agent
wallet and refuse a master key (detectable locally: signer address equal to
account address). Whether an HL agent wallet can withdraw is **unresolved** and
must be verified before any claim ships.

Why this dominates: in the 3Commas breach, ~100,000 exchange API keys leaked
and users lost an estimated $20M+. The keys were the whole attack. Key scoping
would have blunted it; dashboard hardening would not have.

## 6. The seam

**One input contract, many authors.** A human filling a form and an agent
editing a file must produce the same thing, hit the same validator, and get the
same refusal text. No capability exists on one path that does not exist on the
other; the config file remains the source of truth.

- The panel **never writes live config**. It emits a proposal → validates it
  with the engine's own loader (never a second validator — that is the
  duplicate-concept failure this repo exists to kill) → shows a diff and a
  dry-run → a deliberate step applies it.
- The engine is **separately launchable** and self-locking; the panel attaches
  to a running engine or spawns one detached. Closing the browser must do
  nothing. No auto-restart: restarting into an unknown order state can
  double-place.
- Single-instance enforcement belongs **in the engine**, not the panel, so it
  holds when the engine is started by other means — demonstrated by OctoBot's
  counterexample above, where the UI port was doing the job by accident and
  failed open into two live engines.
- **One file is the running configuration.** OctoBot's effective config is a
  merge of two files, so neither shows what is actually running, and hand edits
  made while running are discarded on the next UI save. A panel and a file that
  both claim authorship will drift; the file wins here, always.

## 7. Phases

1. **View.** Renderer over the snapshot and the readout. Zero risk, immediately
   useful, and it forces the vocabulary decisions.
2. **Configure.** Form → validator → diff → dry-run → deliberate apply.
3. **Control.** Start, stop, revive — the engine as sole author of every venue
   write, the panel as an author of intents only.

Each phase is useful alone, and nothing in phase 1 needs to be revisited to add
phase 2.

## 8. Decisions from the design pass (2026-08-08)

- **Setup is bot + watcher, one act.** F1 refuses an unwatched fleet, so the
  create flow emits a single proposal holding the bot entry AND its watchdog
  line; the ceiling pre-fills at cap x1.2 (inside F2's 1.5x bound) and the
  person confirms a number instead of inventing one. Unwatchable
  configurations are unexpressible in the UI — the refusal still exists on
  the file path, with the same text, from the same loader.
- **3Commas: take the form factor, refuse the vocabulary.** The guided
  create-flow and per-bot cards are genuinely good; the names ("take profit
  means start trailing", two profits under one label) are the cautionary
  tale of §1. Their skeleton, our names.
- **Three doors, one house.** UI, hand-edited file, and agent are three
  authors of the same proposal shape, validated by the engine's own loader.
  The dashboard writes nothing the file path cannot express and owns
  nothing; the config file stays the single source of truth. The agent door
  stays open forever; the UI door makes it optional.
- **Deliberately technical, kept that way:** the mainnet double-switch (F7's
  friction is a safety control — the panel displays mainnet state, never
  switches it) and raising a watchdog ceiling past the cap bound.
- **Keys are out of scope for the panel, permanently.** No key entry, no key
  storage, no key material in any request or response — a panel compromise
  steals nothing. Keys stay a hand-placed 0600 env file (one technical step
  for every user, by design); the ENGINE checks its own key's permissions at
  startup (F8's home) and the panel displays only the verdict.
- **Tombstones are dashboard citizens:** shown with their reason; revival is
  a deliberate confirm — the delete-the-entry-on-purpose workflow with the
  evidence attached.
- **Telegram is push, the panel is pull** — same events, same vocabulary in
  both, or the two-names bug is built into our own tooling.

## 9. The backtester (rehearsal, never a promise)

- **One renderer, two sources.** The backtester emits the SAME JSON contract
  as the live readout — same books, columns, names (trips, per-trip,
  realized, fees, bought/sold, zero-spread, max depth). Rehearsal and live
  render through one code path, so comparing them is comparing like with
  like. Commercial backtest and live screens famously disagree; ours cannot.
- **In the create flow:** draft -> engine validator (with watcher) -> venue
  public candles, cached locally -> the engine's own backtester -> readout
  table plus the ladder drawn over the price path. Adjust, re-run, apply.
- **Honesty rules:** show the window, never annualise; state the fee
  schedule used (G16, venue-asked); print the hold benchmark beside every
  result; label it a rehearsal — same candles are not same fills; print the
  known limitation (no bid/ask in the backtest plan, so guard-band drops
  never happen: slightly optimistic) until it is fixed.
- **Refused:** an optimizer. The backtester answers "what would this config
  have done", never "what config should you run". A recommend button is the
  flattering-number machine of §1.

## 10. Build order

1. **Data contract** — `report.py --json` (also adds bought/sold columns to
   the terminal table and gates R9 behind the truncation flag).
2. **View** — localhost panel over snapshots + readout: per-bot state
   (named), position at cost, money columns, watcher health, range strip as
   inline SVG, settlement preview.
3. **Backtest in the create flow** (§9).
4. **Configure** — form -> proposal (bot + watcher) -> diff -> dry-run ->
   deliberate apply.
5. **Control** — start/stop/revive; engine remains sole author of venue
   writes.
