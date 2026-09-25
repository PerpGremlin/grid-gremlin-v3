# Pre-build research — raw notes

The working notes behind the three synthesis docs (`../CONCEPTS.md`, `../ALIGNMENT.md`,
`../LEAN.md`). Each file is the structured output of one focused reading pass, 2026-08-03,
against v2 at `79c7da3` (private repo) or the live web. **The syntheses are the reviewed
surface; these are the evidence trail** — denser, unpolished, occasionally superseded by
a later pass (marked in the syntheses where so). Claims carry a file:line or URL;
inferences are marked INFER. Account figures, holdings and host identifiers are redacted
here — this repo is public; the unredacted sources live in the private v2 repo at the
cited paths.

| file | what it covers |
|---|---|
| [v2-config-layer.md](v2-config-layer.md) | every config key, validator rule and derived value; the dead `take_profit_price`; the unvalidated `leverage`; error messages naming dead keys |
| [v2-strategy-math.md](v2-strategy-math.md) | ladder math, the lot, the split, deadband halves, one-lot-per-rung's three generations, window anchors, 15 duplicates, 27 lying comments/docs |
| [v2-runtime-loop.md](v2-runtime-loop.md) | the cycle end to end, all per-bot state, cooldowns, the `adopt` stop dissection, the fleet-loop `NameError` |
| [v2-exchange-layer.md](v2-exchange-layer.md) | the truth contract field by field, venue/adapter/client layering, Bybit-vs-HL duplicates, watchdog, error taxonomy |
| [v2-research-review.md](v2-research-review.md) | what PRIOR_ART + the five studies actually contain vs what BOTS.md attributes to them; the unimplemented server-side stop |
| [v2-history.md](v2-history.md) | the incident record: every churn fix with measurements, the Camp A/B decision, start-state origins, martingale round bugs, ops constraints |
| [field-grid-bots.md](field-grid-bots.md) | Bybit/Pionex/Binance/OKX grid products: seeding, sizing, range-exit, termination, trailing (primary sources, URLs inline) |
| [field-martingale-bots.md](field-martingale-bots.md) | eight martingale/DCA products: sizing conventions, TP bases, futures scorecard, parameter-name table |
