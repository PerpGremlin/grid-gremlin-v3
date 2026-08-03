# Build journal

One entry per working session. What was done, what was decided, what broke, what's next.
Newest first. Public repo: no account figures, no holdings, no host identifiers.

---

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
