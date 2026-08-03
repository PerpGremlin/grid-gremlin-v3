# PLAN — the build checklist

**Status: skeleton draft, 2026-08-03.** One slice = one PR = one working session; "do
slice N" is a complete instruction because everything a slice needs is here and in
`SPEC.md`. A slice is done when its `done when` line is observably true and the whole
suite is green. Checkboxes and SPEC's `test:` column update **in the same PR** as the
work — these files never describe a state the repo isn't in. `BLOCKED` names the owner
decision that gates a slice (see the ⚠ DECIDEs in SPEC/ALIGNMENT); everything else can
build in order today.

Build direction: pure core outward. No slice touches I/O until slice 6; nothing writes
to an exchange until slice 8; nothing trades unwatched, ever.

---

- [ ] **0 — scaffold**
      builds: T5 groundwork · package layout, spec runner, CI-green empty suite
      done when: `tests/run.py` runs and reports zero specs, zero failures

- [ ] **1 — config doctrine**
      builds: C1–C5, C7 (C6 ⚠ BLOCKED: row-failure policy — build refuse, gate the
      alternative)
      done when: refusal specs green incl. nested objects and near-miss hints; a
      cannot-place config refuses with the reason

- [ ] **2 — contract maths**
      builds: A1–A6
      done when: golden fixtures for linear/inverse/spot rounding, minimums,
      qty-from-notional, position_idx all green; no network anywhere in the module

- [ ] **3 — the lattice, the lot, the split** (pure)
      builds: G1–G6, B8, E1, E4
      done when: hand-computed golden ladders match; prefix-stability spec green;
      spacing/guard check fires on the true minimum gap
      NOT here: exits, caps, martingale

- [ ] **4 — the exit ladder, the caps, the entry guard** (pure)
      builds: G7–G10, G12
      partially ⚠ BLOCKED: G4 (the lot's anchor) — build one anchor behind one named
      function so the decision changes a constant, not a shape
      done when: the start-matrix rows for flat and simple-adopt fixtures green;
      sabotage specs (T1) prove G7 and G9 can fail

- [ ] **5 — the martingale as data** (pure)
      builds: M1, M2, M5
      ⚠ BLOCKED: M2 confirmation (multiplier config), M4 (TP basis — affects fixtures
      only, the ladder itself can build)
      done when: martingale ladders reproduce grid math through the shared functions;
      series-total refusal states the number

- [ ] **6 — truth, one venue**
      builds: V1–V5, E5, E8, I4
      done when: schema-validated truth from live demo; pagination sabotage spec green;
      a failed startup read refuses to trade

- [ ] **7 — diff, apply, identity** (no live writes yet — fake venue)
      builds: E2, E6, E7, I1–I3
      done when: keep/cancel/create/amend decisions green on fixtures incl. truncation
      tolerance and foreign-order immunity; error-kind matrix specced

- [ ] **8 — the loop, the window, events** (first demo trade)
      builds: E3, W1–W3, plus the event vocabulary
      done when: a two-cycle spec (T2) passes; a demo grid places, fills, and re-plans
      with an empty steady-state diff; order events logged, not shipped

- [ ] **9 — the earned guards**
      builds: B3–B7
      done when: each guard's incident is a spec that fails with the guard removed
      NOT here: split hysteresis

- [ ] **10 — split hysteresis**
      builds: B2, B1's naming
      done when: the flap-inverse-to-volatility fixture is quiet with the band on,
      churning with it off; 0 ≡ unset pinned

- [ ] **11 — start states**
      builds: S1–S6, S8 (the matrix, one spec row per cell)
      ⚠ BLOCKED: S3 (seed mechanics), S7 (involuntary flat), B9 (band family's fate —
      determines which adopt cells exist)
      done when: every non-collapsing matrix cell has a green spec; restart-reset list
      written and asserted

- [ ] **12 — the martingale round**
      builds: M3, M6 (M4's decided basis lands here)
      done when: TP-set-before-rest, tp-through-market, repeat-from-flat-only, and
      restart-adoption specs green on demo

- [ ] **13 — stops and stand-down**
      builds: X1–X5
      ⚠ BLOCKED: the §13.4 watch-restructure call; X3 scope (which venue hosts it)
      done when: each stand-down path's on-venue residue is specced; the server-side
      stop refuses where unsupported

- [ ] **14 — fleet and watchdog**
      builds: F1–F6, E3's snapshot half
      done when: both-ways bot/watchdog coverage spec green; dead bots visible in
      snapshots; mainnet flag unreachable from the demo unit

- [ ] **15 — backtest parity and the v2 diff**
      builds: T3, T4
      done when: trade-through fills + funding modelled; v3 `plan()` output diffed
      against v2 on shared fixtures with every divergence either intended-and-cited or
      fixed

- [ ] **16 — the second venue**
      builds: A6's payoff, V-contract reuse
      done when: the venue spec suite passes against the second adapter unchanged
      NOT here: any strategy change — if one is needed, the seam failed and that's the
      finding

---

**Standing rules while building:** every PR updates this file and SPEC's `test:` column
· public-repo hygiene sweep before every push (see CLAUDE.md) · suite green at merge,
no exceptions for config changes (broken twice in v2, both times by configs) · nothing
here reaches a venue with real funds until the owner promotes v3 explicitly.
