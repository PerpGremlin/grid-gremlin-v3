# Build journal

One entry per working session. What was done, what was decided, what broke, what's next.
Newest first. Public repo: no account figures, no holdings, no host identifiers.

---

## 2026-09-25 (night) — D28 PR B: the slide wired live, with its three bounds

**Built.** The live bot carries the window. `Bot.offset` is the lattice offset
(G17); `plan_grid` and the seed read it, every link carries the absolute rung
index (a short's slid window goes negative — `rung_of` parses the sign), so a
slide is one ordinary diff: the rungs that left the window are cancelled, the
rungs that entered are placed, the overlap keeps its order ids. Pinned live
against the fake venue: a one-rung slide of a ten-order ladder is one cancel,
eleven creates, nine orders untouched.

**The three bounds from the evening's replays, all built:**

- **X8 — the stop follows the window.** A slide row's `mark_price` stop is
  `rungs_beyond` the window's near edge, re-derived every cycle from the
  current offset; the server-side stop re-sets itself after a slide because X3
  is level-triggered. An absolute `level` is refused with `slide`, and
  `rungs_beyond` without it. `account_equity` stays absolute.
- **G21 — confirmation.** `confirm_seconds`, required, never defaulted: the
  trigger must hold on every cycle for that long; a ref back inside resets the
  clock. The clock is in-memory (E3). The backtester honours it in whole bars.
  The sabotage spec shows zero confirmation moving the house on one read — the
  ETH control lesson.
- **G22 — the persisted offset.** `logs/slide_state.json`, the second narrow
  local durable fact beside the tombstone and by the same argument (the
  exchange cannot express it). Written BEFORE the orders move; read at build,
  clamped to the row's clamp and side; corrupt fails closed, a failed write
  never blocks the slide. Missing means home — and the spec found the honest
  shape of "a lost ratchet, never lost money": with the market still past the
  trigger a fresh bot simply ratchets back to the same window on its first
  cycle and keeps every order; with the market back inside home, the slid
  window's entries now sit above the ref and are cancelled as any marketable
  buy would be.

**Also.** `check_link_fits` sizes for whichever window edge prints longest
(I3). The build warns above 20× on a slide row — a warning, not a rule; the
fleet-level rule needs the owner's D-number. The range review shifts each
row's bounds by the persisted offset and says so; the snapshot carries a
non-zero offset. 367 specs (18 new, in `tests/spec_slide_live.py`).

**Not done, on purpose.** Nothing has run live — the repo is parked. The
first demo slide is the evidence this needs: the `slide` events, the re-set
server stop, a restart mid-window. BACKLOG §6 says so.


## 2026-09-25 (evening) — D28: the slide, built pure and replayed twice

**Decided (owner).** Re-anchoring is trailing; v3 had deleted it (D10). The
owner chose the **slide** — drop rungs at the near end, add the same number at
the far end, spacing and lot unchanged — with a rung-count trigger, favourable
direction only, inventory untouched, a required clamp. Recorded as D28;
G17–G20 and T6 in SPEC. On the owner's hysteresis worry: a ratchet needs none,
it never returns; the trigger count is the only band. That turned out to be
half right — see the control window below.

**Built.** `ladder.py` gains one lattice with many windows: absolute rung
indices (a slid window's overlap keeps every order's identity), `lattice_price`
/ `lattice_index`, and `slide_offset`, the pure ratchet. `config.py` validates
`slide: {trigger_rungs, max_rungs, ref_position}`. The backtester carries the
offset bar to bar and now rests only the placement window (T6). **The live bot
refuses the key** until it carries the offset (the wiring is PR B). 349 specs.

**Backtester fidelity (T6).** Applying the window and dropping from hourly to
five-minute bars halved the replayed ETH short's phantom inventory and cut the
BTC long's frozen income from 10.6k to 4.8k against a live 2.6k — closer, still
optimistic: a live fast move skips rungs the replay fills. The short-side gap
is fidelity, not a bug; replays are read as an upper bound.

**Replay 1 — the 48-day rally, real rule, 5-minute bars, maker fee, ratios of
each bot's own capital:**

| long grid (demo leverage) | frozen net | slide net | frozen maxDD | slide maxDD | ladder used |
|---|---|---|---|---|---|
| BTC (75×) | +10% | +140% | 26% | **179%** | 13% → 37% |
| ETH (55×) | +14% | +172% | 11% | 89% | 11% → 44% |
| SOL (10×) | +2% | +43% | 4% | 24% | 10% → 48% |

The slide multiplies a long grid's income by ten in a trend, and deploys three
to four times as much of the ladder doing it — so the drawdown scales with it.
At the demo's 75× the BTC slide would have been liquidated on the 15 September
dip. At 10× (SOL) the ratio is healthy. K = 1, 2 or 4 barely matters;
`ref_position` 1.0 slides more often for a little more income; 0.25 trims
drawdown. The shorts never slid — a short slides down only and the market went
up — and lost on inventory as before. Correct, and useless in a rally.

**Replay 2 — the control: the flattest 48 days in the last year (2025-08-15 →
2025-10-01, BTC drifted +0.7%), same three grids re-centred, leverage 10:**

| symbol (drift / range) | frozen net | slide net | frozen maxDD | slide maxDD | slides |
|---|---|---|---|---|---|
| BTC (+0.7% / 10%) | +1.3% | +1.3% | 6% | 6% | 0 |
| ETH (−4% / 25%) | +12.9% | **+5.1%** | 23% | **55%** | 1 |
| SOL (+15% / 40%) | +12.3% | +26.1% | 7% | 42% | 3 |

Flat: the ratchet does nothing, as designed. ETH is the lesson: one early
spike two rungs past the top slid the window up, the spike reversed, and a
window that never retreats bought the whole way down from the higher
perch — half the income, twice the drawdown. That is the owner's hysteresis
worry, real, in a different shape: a ratchet cannot flap, but it can be
**fooled once**, and two rungs of a 0.24% lattice is a 0.5% excursion.

**What this says.** The slide converts a range strategy into a trend strategy:
it earns in trends, idles in flat markets, and pays in spike-and-reverse
regimes with the drawdown of a full ladder bought high. Three things bound
that, none built yet: the **stop must follow the window** (an absolute stop
level below the home range is meaningless once the window has left it — the
level should be rungs below the window), a **confirmation** before a slide
(time or bars beyond the trigger, so a wick does not move the house), and
**leverage sanity** in the config (a slide at 75× is a liquidation with extra
steps). All three go into PR B's wiring list. The replay-only refusal stands
until then.


## 2026-09-25 (later) — post-mortem: what a fixed-range fleet did in a 31–62% rally

Measured, not recalled: venue fills with their type, closed-P&L records,
the per-minute snapshots, hourly candles, and the backtester replayed over
the same 48 days. Test funds throughout; figures are ratios of each bot's
own capital so the mechanics survive the public-repo rule.

**The market.** Every symbol the fleet traded rose between 31% (BTC, ADA)
and 62% (SOL) from the 2026-08-08 restart to the 2026-09-25 shutdown, with
no retrace deep enough to re-enter a range once left.

**The fleet's life was eleven days.** Grid fills per week: ~144, 45, 44,
then zero for the remaining four weeks. The last grid fill was 2026-08-21.
Long grids sold their last lot leaving the top of their range and sat flat
above it; short grids filled to their inventory cap on the way up and sat
offside below it. Thirty-five of forty-eight days had no grid activity.
G11 (idle outside the range) worked as designed, and the daily range review
proposed a wholesale re-anchor from 2026-08-19 on; nobody was there to do it.

**Where the money went.** Grid trips inside the window closed positive —
about +4% of committed capital, seventy percent of it in the first eleven
days. Funding netted to zero across the fleet (the BTC long paid what the
ETH short received). The inventory the grids were CARRYING did the rest:
the big BTC long leg's held stack gained about +54% of its capital over the
window, the big ETH short leg's held stack lost about −59% of its capital,
the small hedge legs moved with their sign. Net for the six fixed grids over
the window: roughly −8% of committed capital. **The hedge pairs were
asymmetric by design (experiment 2, big leg + small leg) and the two big
legs pointed opposite ways — the fleet's P&L was the difference between two
directional bets, not grid income.**

**The equity curve lied.** Demo equity rose ~16% over the window while the
bots lost. The unified demo wallet carries seeded spot holdings no bot owns
(a gold token among them) and they rose with everything else. The snapshot
equity is a wallet number, not a fleet number; the readout's D8 split is the
only honest instrument and it said so on 2026-08-25.

**Martingales.** The ADA looper made 692 owned fills plus hosted-TP closes
and finished slightly negative after fees on its capital — 59 same-rung exits
(R9) and two-thirds of its fills at taker rate. The DOGE doubler closed its
rounds positive. Neither reached ten rounds by the SOAK definition because
rounds never fully re-armed — a readout question queued in BACKLOG §6.

**Fees, live.** Maker ~2.1 bp, taker ~5.5 bp on Bybit demo. 67% of all trade
fills in the window were taker — nearly all of them the martingales' market
entries and hosted-TP closes, not the grids.

**The replay** (T3 backtester, hourly bars, maker fee, same window, six
linear grids):

| variant | BTC long | ETH long | SOL long |
|---|---|---|---|
| as configured, grid net | 1× | 1× | 1× |
| re-anchored weekly to price (approx.) | ~6× | ~7× | ~8× |
| range 3× wider, same rungs | ~0.9× | ~0.3× | ~0.6× |

Re-anchoring is the lever, by a large margin; wider ranges only thin the
ladder. For the short grids every variant loses on inventory in a rally and
re-anchoring loses MORE (each week shorts again, higher). A short grid is
not a hedge against a trend; it is a short. **Caveat on the shorts: the
backtester carried three times the short inventory the live bot was capped
at — its short-side numbers are not usable until that is understood
(BACKLOG §6).**

**The HL "liquidation" was not one.** Both HL grid deaths trace to one
misread: HL stamps a `liquidation` object on BOTH sides of a liquidation
trade, and `exchange/hyperliquid/truth.py` treats any such fill as a venue
liquidation of *us*. On 2026-08-13 and 2026-08-19 our resting exits filled
against someone else's liquidation (`liquidatedUser` is a different address
each time; both closes were tiny and profitable), and the engine killed a
healthy bot on each — one labelled "liquidation", one "outside close"
because the disowned fill looked like an outside hand. The SOAK freeze on
HL calls lifts; the defect is an engine item (BACKLOG §6). The DOGE stop and
the AVAX TP-and-stop were correct.

**What this says.** A fixed range on a trending market is idle within days,
and what it holds while idle is a directional position sized by the grid's
capital — the "hedge pair" experiment turned into two opposite bets of
different sizes. The one operational change with evidence behind it is
re-anchoring, which v3 deliberately left to a human (D10). The human was
away for 48 days. Whether that becomes a rule in the engine is a new
decision for the owner, not a reinterpretation of D10.


## 2026-09-25 — the 48-day readout, then everything off

**Found.** No session between 2026-08-08 and today. Both fleets (Bybit demo,
HL testnet) ran the whole gap on one process each: no restart, no engine
traceback. HL's testnet API threw tens of thousands of lost cycles (502s,
rate-limit streaks); the engine rode them all. That is the first real
reliability evidence v3 has, and it is clean.

**What the run did NOT deliver.** No experiment reached the SOAK minimum (a
grid's 50 exit fills, a martingale's 10 rounds), so nothing on the board was
called. The market trended hard through the window; nine of twelve demo grids
sat above their fixed ranges for most of it, idle by design (G11) and useless
in practice. Nearly every fill in the fleet came from one martingale that paid
more in fees than it realized — 59 same-rung exits flagged by R9. The equity
curve rose on inventory the grids were holding by accident, not on grid profit
(D8 separates them; the readout is unambiguous).

**Kills, as the SOAK doctrine requires them explained here.** Demo XRP short:
server-side stop fired at its level on 2026-08-20 and flattened venue-side
before the bot's own cycle saw it — **X2 is proven live** (BACKLOG §2 closes).
HL ETH short: position closed by an outside actor, 2026-08-13 (D1 kill, correct).
HL AVAX martingale: round complete on TP, repeat off, 2026-08-15 (by design).
HL DOGE short: stop fired, flattened, 2026-08-20 (correct). **HL BTC long:
closed by liquidation, 2026-08-19 — unexplained.** The position was tiny and
the account was far from its maintenance floor; the leading suspicion is the
venue's testnet margin handling, not the engine, but a liquidation is a
liquidation. It stays a freeze on any HL parameter call until understood.

**Ops defects the gap exposed** (BACKLOG §6):
1. Dead bots keep their last believed position in the snapshot. The watchdog
   read that frozen belief and paged the same breach every re-alert window for
   the whole 48 days, about a bot that had closed flat. The range review had
   the same blindness and said so itself on 2026-08-25.
2. The Claude token the range review and triage depend on expired on
   2026-08-26. Both failed silently every day after: an "authenticate" line in
   a log nobody reads. An unattended ops layer that dies quietly is worse than
   none.
3. The fleet log has no rotation; 48 days of one-second cycles is a
   multi-gigabyte file.
4. The watchdog bound for the AVAX martingale was wrong from the start —
   the breach pre-dates the gap.

**Decided (owner).** Everything off: every unit and timer stopped and
disabled, then every order cancelled and every position flattened on both test
accounts (verified: zero orders in every category, zero positions on either
venue). The venues confirmed the phantom — the XRP short had been flat since
its stop. Nothing trading-related runs or rests anywhere. v2 remains parked.

**Then a stock-take.** The engine is the asset: ~5,400 lines, stdlib only,
335 specs green. The rot is around it: an ops stack that pages on phantoms and
dies on a token, and a document pile that outweighs the code. So: CLAUDE.md
(local, gitignored) rewritten to stop claiming this is the dissection phase;
the eight finished documents and the research notes moved to `docs/archive/`
with every citation re-pointed; the living seven stay in `docs/`.

**Next.** Not a restart. The unanswered question is older than v3: whether
fixed-range grids on a trending market are a strategy at all. The backtester
and 48 days of snapshots can answer it offline before anything is pointed at a
venue again.

---

## 2026-08-05 (later) — the unbiased eyes

**Done.** The owner asked for an audit by fresh eyes: two independent agents,
zero build context, read-only, told to DEMONSTRATE what they claim. Both earned
their keep. The docs auditor's worst find: the README still said "no mainnet
path — not a flag, an absence", denying the very armour built that morning —
the repo's own failure mode, on the safety-critical claim, caught in hours. The
README gained a Safety section, everything shipped since slice 16, and a spec
now scans configs/ so no fleet file can ever carry `allow_mainnet`. One dead
config key (`cancel_orders_on_exit`) deleted.

**The code auditor demonstrated four HIGHs, all in the newest code**: an
epoch-0 fills pull (~3,000 requests per call, re-fired every cooldown cycle);
the partial server-side SL never re-sizing as the position grows (and the spec
ASSERTED the absence — a spec testing the bug); tranche maintenance cancelling
conditionals it didn't own (a hedge pair would wage a mutual-cancellation war);
and round-completion mis-detection (phantom round counters, event spam, and the
new base firing before the old safety ladder was cancelled — E2 violated across
rounds). All fixed: bounded 30-day history read once per completion; cancel-
then-set resize with ownership by position index; the completion latch; cleanup-
before-open. Plus the mediums: spot base-coin fees quote-normalised in the
ledger (M2), tombstones fail CLOSED on corruption but a failed write never
blocks the flatten (M3), the loop survives ANY exception (M4), kill pages flush
immediately (M6), the backtester refuses non-linear maths by name (M8), the
fleet-file lock lands before build's account writes (L1), and five smaller
honesty fixes. One documented limitation (M5a): a hosted-TP martingale cannot
distinguish a manual close from its own TP — `assumes_sole_actor`, stated.

**Lesson.** Six of the audit's findings were masked by specs that tested the
wrong thing — including one asserting the buggy behaviour. Fresh eyes are not a
luxury; they are the only reviewer the author cannot pre-agree with.

---

## 2026-08-05 — the day the safety systems earned their names

**Done.** Slices 26-32 in one day, all owner-directed: the backtest CLI on
fresh venue bars (A6 refused the first draft — the sabotage spec defending the
architecture against its author); 1s polling (D22 — the venue's rate budget is
the pace, WS wake dies by decision); inverse live (a BTC-margined BTCUSD grid;
A4's maths with money-shaped numbers); the armed switch (D25/F7 — mainnet
exists, cold, double-safetied, PROMOTION.md is the checklist); margin spot
(D24 — the signed balance IS the position, an ADA borrow-long soaking);
martingale tranches + trailing (D23/M10/M11 — hosted on Bybit's conditional
book, several D21 exits on HL; an ADA tranche martingale opened round one with
its trailing stop riding the venue). The readout caught its own inverse-unit
bug (linear math on $1 contracts: a −121,570 phantom for a −1.59 truth — A4
reaches the ledger now).

**The stop-fire test (owner-authorized).** Preparing it exposed the gap that
mattered: alive=False lived only in memory — a restart would have revived a
stopped bot straight back into the market, ALIGNMENT's undesigned fifth start
state. SPEC X7: a tombstone durable BEFORE the flatten, dead-and-visible at
build, revival only by deliberate operator act. Then the live fire, XRP short:
stop hit on cycle one → flattened 1334.1 at market → 6 owned orders cancelled
→ kill paged with the residue stated → tombstone written → and on the second
restart the bot BUILT DEAD, naming its tombstone. PROMOTION's "a stop has
fired end-to-end live" box: ticked. XRP revived deliberately with a fresh
clock and a server-side stop so X3 stays exercised.

**Broke / caught.** Two overnight TLS resets each killed the HL process — E7
now holds at the fleet loop (a failed read costs the cycle, never the
process). Spot fee dust (8.85e-06 LTC) counted as "holding" — flat below the
venue minimum now, symmetric around zero. One staging error shipped specs
without their code for one commit — caught by the box suite, fixed in the
next.

**Next.** Reinvest + round-cooldown design discussion with the owner; signal
starts deferred (owner does their own TA); soak clocks run.

---

## 2026-08-04 — phase 2 opens: the readout finds its first bug, and a venue moves the ground

**Done.** `BACKLOG.md` (the ledger of what v3 doesn't do; items leave only via
building PR or killing decision), then slices 18-22: the **readout**
(`python3 -m gridgremlin.report`, SPEC R1-R5 — venue fills, average-cost ledger,
grid profit vs total P&L per D8, read-only by construction); **market-order
identity** (SPEC I5); **ops templates** (`ops/`); **spot live** (SPEC V6 — the
wallet holding synthesized as the position, spot-safe bodies,
`marketUnit=baseCoin`; an LTC grid joined the demo fleet and rested its ladder
first try, cross guard catching the rung at the ask); **the soak doctrine**
(`SOAK.md`, the experiment registry). Basis precedence pinned after the owner's
correction: the config field exists BECAUSE demo/spot venues keep no basis
(v2 design); truth overrules it where reported — two specs. Margin spot
recorded in BACKLOG as a decision-first item. Suite 232.

**Broke / caught.** (1) The failure alarm paged once per 30s retry through a
venue outage — OnFailure re-fires on every failed start under
StartLimitIntervalSec=0; alerts now stamp-file rate-limited (one page/30min),
captured in the templates. (2) The readout's unowned bucket immediately
exposed that seed/base/flatten orders carried no identity — slice 19 within
the hour; the tool found the bug it was built to find, on day one. (3) The
venue outage ended with the ground moved: **HL removed XRP from its testnet
universe mid-soak** — the build crashed as a bare StopIteration; now a named
refusal (C7 spec), and AVAX took the martingale row. On restart the four HL
grids re-adopted their pre-outage ladders with zero churn, and **D21's live
proof completed**: base at market, rung-0 reduce-only TP resting venue-side,
1.5× safety ladder below — all identity-linked.

**Next.** Triage-on-failure (v2's fourth layer), the relay, backtest kline
fetch; the doctrine's minimum samples now govern when the A/B questions get
called.

---

## 2026-08-04 — the VPS: pipeline and the watch

**Done.** v3 cloned onto the VPS beside the parked v2 (which stays untouched at its
good commit); the work-here-push-pull-there loop proven — and its first run caught the
T4 parity specs hardcoding workstation assumptions, fixed via the loop itself. The v2
watchdog setup replicated for v3: fleet unit (Restart=always, OOM-sacrifice-first,
OnFailure Telegram alarm), watchdog oneshot + 5-minute timer in its own slot
(SuccessExitStatus=1 — a paged breach is the unit succeeding; only a crash alarms),
watchdog-broken alarm, and the watchdog now pages Telegram directly with v2's
send-before-persist discipline. The demo fleet runs CONTINUOUSLY on the box now — and
its first cycle re-adopted the ladders the workstation had placed, across machines,
by identity, zero churn. Discipline note: the demo account's single process lives on
the VPS henceforth; workstation demo runs only with the unit stopped.

**Next.** Soak. The watchdog watches; the phone hears; the owner reads.

## 2026-08-04 — build day: slices 0-8, first live trade

**Done.** Eight slices in one session, each its own merged PR, suite growing 0 -> 115
specs: scaffold, config doctrine, contract maths, the ladder (lattice/lot/split), the
plan level (exits/caps/entry guard), the martingale as data, Bybit truth, diff/identity,
and the loop. The demo grid ran live: 21 post-only entries, 25 consecutive cycles of
empty steady-state diff, then a real fill -> fill event shipped -> a reduce-only exit
one lot, one rung above, its price pushed by the fee floor exactly as G6 specifies.

**Caught along the way** (both directions): C7 refused two of my own draft error
messages for quoting retired keys; a spec fixture had the short-in-profit floor wrong;
the exit-ladder pour lost a qty-step per iteration to float-floor residue (rebuilt in
integer steps) and dropped sub-minimum first shares (they now walk outward). The owner
called the draft docstrings "long and confounded" — prose stripped to SPEC ids; the why
lives in one place now.

**Observed, expected.** With no guards built yet, the live run reproduced v2's #41
boundary churn: the mark wobbling across the held rung shifts the suppression prefix and
cancel/re-places the neighbour entry each crossing. The incident arrived exactly where
the plan said it would — slices 9 (flap cooldown) and 10 (split hysteresis) are its
scheduled cure, and now have a live fixture to verify against.

**Next.** Slice 9 — the earned guards.

## 2026-08-04 — postscript: comms and the HL write path

**Done.** Telegram keys ported and the sink built (coalesced, >=3s, order mechanics
stay in the log — the July-30 channel lesson); first live message delivered. HL flipped
to testnet-only structurally (mainnet unconstructible — the owner manages real
positions there; the mainnet agent key was deliberately never copied). Then the owner
provided a testnet agent key and the write path landed: v2's earned signing stack
carried verbatim (SDK golden vectors pass bit-for-bit), the write client ported with
v3 error kinds, a venue facade behind the Bot's unchanged surface — and the last
venue coupling left the engine: bot.py now imports no venue at all. Live smoke on
testnet: an order placed, rested, and cancelled by id. Then the faucet claim: the mock
USDC surfaced in the SPOT clearinghouse — HL's unified account mode — and v2's
mode-aware wallet arithmetic (with its measured no-double-count rule) was ported and
specced. The sized-like-real-life fleet launched: 400 of 999 USDC at 5x, stop below
the range, watchdog required. **A real bug on the first run**: the HL truth read
returned raw cloid hex as link_id — the diff could not recognise its own orders and
re-placed the ladder every cycle. The guards contained it (flap cooldown + margin
ceiling capped the bleed at 19 duplicates), the book was cleaned, the missing
cloid_to_link decode ported from v2, and the incident pinned in the venue-contract
spec. Re-run: nine placed, then empty steady-state diffs; watchdog ok. 'skip' joined
the order-mechanics kinds so the guard-band rung stops paging the phone.

## 2026-08-04 — the build completes: slices 9-16

**Done.** The second half of the checklist in one continuous run, each slice a merged
PR, the suite growing 115 -> 199 specs: the earned guards (each with its incident as a
sabotage spec), split hysteresis (the slice-8 live churn, cured and pinned), the start
matrix (seed built; involuntary flat decided into existence), the martingale round
(TP-as-venue-truth — the restart-rewrites-a-round bug class deleted by architecture),
stops (flatten-and-kill, the floor core provably surviving; server-side partial SL —
the liquidation study's #1 TAKE, finally real), fleet and watchdog (validated, coverage
both ways, one-process lock, the dead visible), backtest parity (trade-through, funding,
the honesty case), and the finale: Hyperliquid across the seam.

**The two proofs that close the project's argument.** T4: v3's planner diffed against
v2's actual code on shared fixtures — exact match everywhere except the single divergence
a decision ordered (D5), cited by number. A6: the second venue landed without touching
one strategy file, pinned by a source scan; the HL adapter inherits the linear maths as
the SAME function objects. The vocabulary held; the seams held.

**Safety note.** The HL package is read-only by construction — no signing code exists in
v3 and the private key was never copied; the owner manages real positions on that
account, and v3 can only look.

**Caught this half.** The exit-link tracker that would have killed a bot on a fast
harvest; the pour's float-floor step loss; JSON stringifying position keys so the v2
diff harness saw no position (partial truth in miniature); and a steady drumbeat of my
own spec arithmetic corrected by the code it was testing.

**Next.** The engine is feature-complete against SPEC. What remains before promotion is
operational: soak time on demo, the deferred list (D15), HL writes when the owner says
so, and the owner's own reading of all twenty-three PRs.

## 2026-08-04 — decisions day

**Done.** The owner read the full pre-build surface and answered every open call —
first in a written response, then a four-question follow-up for the two items that
needed explanation (the lot's anchor, the bad-row policy) and the two conflicts worth
surfacing (stop scope vs the floor core, deadband knob vs emergent behaviour). All
twenty decisions recorded in `DECISIONS.md`; every ⚠ DECIDE in SPEC resolved in place;
all sixteen PLAN slices unblocked, venue order fixed (Bybit → Hyperliquid).

**Decided — the headlines.** A stop is now the off button: flatten grid inventory (the
floor core survives), cancel, kill, never restart — deliberately overturning v2's
"the bot never closes a position." The deadband ships as zero keys: the dissolving
suppression the owner described is exactly what the replenish invariant plus the floor
already produce. The martingale adopts 3Commas vocabulary wholesale and loses its range
bounds (depth derives from the deviation schedule; risk stated as required capital).
Trail is deleted. Seeding is a flat-start toggle, market-order, sized by where the mark
sits in the range. A bad fleet row refuses the whole fleet.

**Noticed.** Three of the owner's answers dissolved questions rather than picking
options: the deadband description turned out to be the entry-guard invariant restated,
the 3Commas adoption made the martingale's cap/floor/naming questions moot, and "call
them safety orders" was the field's own answer. Decisions that remove concepts beat
decisions that configure them.

**Also done, same day.** The migration map (`MIGRATION.md`) — method step 2 — frozen:
every v2 name to exactly one fate (keep / rename / restructure / retire / new / defer),
each row citing its authority, with the complete refusal table as the execution
checklist. The owner pressed on adoption safety twice; the result is G13 ("no planned
order is ever marketable") with sabotage tests for both adoption cases — a concern
turned into a named invariant instead of a config knob.

**Next.** PLAN slice 0 — the scaffold. Code begins.

## 2026-08-03 — dissection day

**Done.**
- Repo recreated clean after working notes were accidentally published in the first
  version. Lesson re-learned from v2's own changelog: *a commit is a publication.*
  Local-only files are now gitignored from the first commit.
- **The concept inventory** (`CONCEPTS.md`, PR #1): every concept in v2 at `79c7da3`,
  one proposed v3 name each, unit in the name, every v2 alias; the internals dossiers
  (sticky ref, windowing, deadband halves, one-lot-per-rung's three generations, the four
  "adoptions", truth/plan/apply); the `adopt` stop finally dissected — a read-only mirror
  of the venue position's stop-loss, proposed rename `stop: {watch: …}`. Method: four
  parallel read-only dissection agents (config / strategy math / runtime loop / exchange
  layer), every claim traced to a file:line.
- **Five live defects found in v2 HEAD**, all from one half-applied rename: the fleet
  loop dies with `NameError` after one cycle, the backtester is dead, the absolute
  martingale TP is validated but never read (a round rests **no exit**), plus two CLI
  crashes. Mainnet runs an earlier commit; **do not deploy v2 HEAD.**
- **The alignment draft** (`ALIGNMENT.md`, PR #2): what a grid *is* (the creed, the
  formal model, and the explicit 2026-07-20 Camp B netted-vs-paired decision — recovered
  from the testing docs after a first pass wrongly called it undecided); the martingale
  sizing question; four start states plus the undesigned fifth (involuntary flat — today
  a fired exchange-side stop leaves the grid re-entering the market); five ⚠ DECIDEs.
- **The field study** (`LEAN.md`, PR #3): v2's feature inventory tiered by what shipped
  configs actually use (~a third of the engine serves keys nothing sets); a faithful lean
  copy estimated at ~half the size, one venue, adapter seam kept; commercial grid and
  martingale/DCA products surveyed from primary sources. Headlines: seeding is
  field-universal (market-buy one lot per rung above price, at creation); the martingale
  genre speaks multiplier-of-previous — the owner's original definition — so the
  recommendation flipped to multiplier-as-config + budget-invariant-in-validator; a new
  decision surfaced (TP basis: v2 uses the round's anchor, the whole field uses average
  entry); range-exit idle is field consensus.
- Raw research notes preserved under `docs/research/` (redacted for the public repo).

**Decided.** PRs #1 and #2 merged by the owner's instruction; the ⚠ DECIDEs remain open —
the owner is writing a response document against them.

**Broke / caught.** The first push of the raw research notes contained live-account
figures and host identifiers; caught before merge on the owner's "this repo is public"
warning, branch rewritten, files redacted. The same class of leak that motivated the
repo's recreation this morning — twice in one day is the argument for a pre-push
hygiene check, added to the working rules.

**Next.** Owner's response doc answers the ⚠ DECIDEs → freeze the v2→v3 migration map
(method step 2) → `SPEC.md` (numbered invariants) + `PLAN.md` (slice checklist) → build
the walking skeleton beside v2 and diff `plan()` against it.
