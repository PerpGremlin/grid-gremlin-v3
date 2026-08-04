# Build journal

One entry per working session. What was done, what was decided, what broke, what's next.
Newest first. Public repo: no account figures, no holdings, no host identifiers.

---

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
