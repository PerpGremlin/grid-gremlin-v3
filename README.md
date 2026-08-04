# grid-gremlin v3

A grid/martingale execution engine, built vocabulary-first: **one set of names shared by
code, config, docs, and tests**, settled on paper before any code was written.

**Status: building.** The paper phase is complete and frozen; the engine is being built
in slices.

| read | to learn |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | every invariant the engine must hold, by stable ID |
| [docs/PLAN.md](docs/PLAN.md) | the build order — one slice, one PR |
| [docs/DECISIONS.md](docs/DECISIONS.md) | the owner's twenty decisions, D1–D20 |
| [docs/MIGRATION.md](docs/MIGRATION.md) | every v2 name → its v3 fate, frozen |
| [docs/CONCEPTS.md](docs/CONCEPTS.md) | the dissection of v2 that started it all |
| [docs/JOURNAL.md](docs/JOURNAL.md) | the build journal, one entry per session |

Run the spec suite: `python3 tests/run.py`

*This repo is public and deliberately carries no account figures, no live position data,
and no deployment identifiers.*
