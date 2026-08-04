# The soak readout doctrine

Measure before theorising: every parameter question the fleets are running gets
its metric, its instrument, and its call condition written down *before* the
numbers look interesting. A call happens in a JOURNAL entry with the numbers,
then one PR changes configs. **No mid-experiment config edits** — an incident
fix restarts that bot's clock, and says so.

## Instruments

`python3 -m gridgremlin.report` (grid profit vs total P&L, D8) · the snapshot
file (equity, mm_rate, per-bot positions over time) · the fleet log's cycle
counts (amends/cancels/skips = churn) · the watchdog record (breaches, kills).

## Minimum sample — no call before

- a grid bot: **7 days AND 50 exit fills**
- a martingale: **10 completed rounds**
- any watchdog breach or kill event freezes calls until explained in JOURNAL

## The questions on the board

1. **Hysteresis** — 0.3-band sized grids vs the no-hysteresis weighted SOL vs
   the 0.15-band tight-window XRP. Metric: churn per exit fill; grid profit
   per day per 1k capital. *Cross-symbol, so directional only: a call needs a
   large, consistent effect.*
2. **Hedge pairs** — BTC long+short, ETH short+long. Metric: pair combined
   grid profit vs the big leg alone; net-position drawdown through moves.
3. **Martingale shape** — gentle looper (1.5×, 0.8% dev, 4 SOs, repeat) vs
   doubler (2×, 1% dev, 3 SOs, one round). Metric: rounds/day, time-to-TP,
   peak margin per round.
4. **Spot vs linear** — the LTC spot grid. Metric: fee share of grid profit
   (spot fees differ), fill/churn parity with the linear grids.
5. **Venue parity** — HL grids vs Bybit grids at matched shapes; D21's
   resting-limit TP fill quality (trade-through wait) vs Bybit's hosted TP.
6. **Weighted vs equal rungs** — the weighted seeded SOL long vs equal-sized
   peers. Metric: grid profit per capital-day; inventory utilisation.

Anything measured that this file doesn't list gets added here first — the
doctrine is the experiment registry.
