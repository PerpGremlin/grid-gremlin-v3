# PLAN — the build checklist

**Status: unblocked, 2026-08-04 — every gating decision is made (`DECISIONS.md`); all
sixteen slices are buildable in order.** One slice = one PR = one working session; "do
slice N" is a complete instruction because everything a slice needs is here and in
`SPEC.md`. A slice is done when its `done when` line is observably true and the whole
suite is green. Checkboxes and SPEC's `test:` column update **in the same PR** as the
work — these files never describe a state the repo isn't in.

Build direction: pure core outward. No slice touches I/O until slice 6; nothing writes
to an exchange until slice 8; nothing trades unwatched, ever.

---

- [x] **0 — scaffold** *(PR #7)*
      builds: T5 groundwork · package layout, spec runner, CI-green empty suite
      done when: `tests/run.py` runs and reports zero specs, zero failures ✓

- [x] **1 — config doctrine** *(PR #8)*
      builds: C1–C7 (C6 decided: a bad row refuses the whole fleet)
      done when: refusal specs green incl. nested objects and near-miss hints; a
      cannot-place config refuses with the reason ✓ (25 specs)

- [x] **2 — contract maths** *(PR #9)*
      builds: A1–A6
      done when: golden fixtures for linear/inverse/spot rounding, minimums,
      qty-from-notional, position_idx all green; no network anywhere in the module
      ✓ (38 specs total)

- [x] **3 — the lattice, the lot, the split** (pure) *(PR #10)*
      builds: G1–G6, B8, E1, E4
      done when: hand-computed golden ladders match; prefix-stability spec green;
      spacing/guard check fires on the true minimum gap ✓ (53 specs total)
      NOT here: exits, caps, martingale

- [x] **4 — the exit ladder, the caps, the entry guard** (pure) *(PR #11)*
      builds: G7–G10, G12, G13's plan-level half (G4 decided: ref-priced lot)
      done when: the start-matrix rows for flat and simple-adopt fixtures green;
      sabotage specs (T1) prove G7, G9 and G13 can fail — incl. the two adoption
      cases: in-profit emits no sell below ref, underwater emits no order between
      mark and basis ✓ (68 specs total)

- [x] **5 — the martingale as data** (pure) *(PR #12)*
      builds: M1, M2, M5, M8 (3Commas vocabulary per D11; no range bounds)
      done when: martingale ladders reproduce grid math through the shared functions;
      series-total refusal states the number; deviation-step schedule specced
      ✓ (81 specs total)

- [x] **6 — truth: Bybit** (D19) *(PR #13)*
      builds: V1–V5, E5, E8, I4
      done when: schema-validated truth from live demo; pagination sabotage spec green;
      a failed startup read refuses to trade ✓ (94 specs; live demo check passed)

- [x] **7 — diff, apply, identity** (no live writes yet — fake venue) *(PR #14)*
      builds: E2, E6, E7, I1–I3
      done when: keep/cancel/create/amend decisions green on fixtures incl. truncation
      tolerance and foreign-order immunity; error-kind matrix specced ✓ (109 specs)

- [x] **8 — the loop, the window, events** (first demo trade) *(PR #15)*
      builds: E3, W1–W3, plus the event vocabulary
      done when: a two-cycle spec (T2) passes; a demo grid places, fills, and re-plans
      with an empty steady-state diff; order events logged, not shipped
      ✓ (115 specs; live: 21 entries placed, 25 empty-diff cycles, one fill ->
      reduce-only exit one rung up; the #41 boundary churn reproduced as
      predicted -> slices 9/10)

- [x] **9 — the earned guards** *(PR #16)*
      builds: B3–B7, G13's placer/venue half (cross guard + post-only rejection path)
      done when: each guard's incident is a spec that fails with the guard removed
      ✓ (126 specs; live fleet steady under guards)
      NOT here: split hysteresis

- [x] **10 — split hysteresis** *(PR #17)*
      builds: B2, B1's naming
      done when: the flap-inverse-to-volatility fixture is quiet with the band on,
      churning with it off; 0 ≡ unset pinned ✓ (132 specs)

- [x] **11 — start states** *(PR #18)*
      builds: S1–S8 (the matrix, one spec row per cell; seed per D9, involuntary flat
      per D1, emergent suppression per D6)
      done when: every non-collapsing matrix cell has a green spec; restart-reset list
      written and asserted ✓ (148 specs)

- [x] **12 — the martingale round** *(PR #19)*
      builds: M3, M4, M6 (TP from average entry)
      done when: TP-set-before-rest, tp-through-market, repeat-from-flat-only, and
      restart-adoption specs green on demo ✓ (155 specs; live round opened on demo:
      base at market -> venue TP at avg x 1.01 -> doubled safeties resting)

- [x] **13 — stops** *(PR #20)*
      builds: X1–X6 (flatten-and-kill per D1; grid-inventory scope per D2; watch
      restructure per D3)
      done when: each stop path's on-venue residue is specced; server-side refuses
      where unsupported; the floor core provably survives a stop ✓ (166 specs)

- [ ] **14 — fleet and watchdog**
      builds: F1–F6, E3's snapshot half
      done when: both-ways bot/watchdog coverage spec green; dead bots visible in
      snapshots; mainnet flag unreachable from the demo unit

- [ ] **15 — backtest parity and the v2 diff**
      builds: T3, T4
      done when: trade-through fills + funding modelled; v3 `plan()` output diffed
      against v2 on shared fixtures with every divergence either intended-and-cited or
      fixed

- [ ] **16 — the second venue: Hyperliquid** (D19)
      builds: A6's payoff, V-contract reuse
      done when: the venue spec suite passes against the second adapter unchanged
      NOT here: any strategy change — if one is needed, the seam failed and that's the
      finding

---

**Deferred by decision (D10, D15)** — not slices, listed so they aren't re-invented:
trail/SMA machinery (range edits do it), partial TPs, trailing TP, signal
start-conditions, profit reinvest, cooldown tuning.

**Standing rules while building:** every PR updates this file and SPEC's `test:` column
· public-repo hygiene sweep before every push (see CLAUDE.md) · suite green at merge,
no exceptions for config changes (broken twice in v2, both times by configs) · nothing
here reaches a venue with real funds until the owner promotes v3 explicitly.
