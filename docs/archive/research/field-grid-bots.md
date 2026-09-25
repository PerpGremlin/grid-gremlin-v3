# Agent report: commercial grid bots (web research, 2026-08-03)

Sourcing caveats: bybit.com help center timed out → bybitglobal mirror; Pionex zendesk 403 → official blogs + search excerpts + one third-party guide (flagged).

## Bybit Spot Grid
- SEED: YES — market-buys base at creation ("automatically buy the corresponding base token needed… by placing market orders"). Equal BASE QUANTITY per grid (1 BTC per level regardless of price). Initial buy = per-grid qty × sell rungs above current. Can FAIL on slippage ("average filled price of the initial market buy order is higher than expected"). "In Base Token" funding converts existing quote/uses held base.
- Params: upper/lower, grid count, total investment; spacing an OUTPUT. Arith+geo (geo confirmed indirectly).
- Profit: buy at N → sell at N+1; "Grid Profit" (per-pair realized) vs "Total P&L" (can diverge in sign).
- Range exit: SUSPENDS, no new orders, resumes on return (idles). Termination: funds to Funding Account; settlement choice BTC+USDT / all-USDT / all-BTC → selling the seed is optional via settlement choice.
- Trailing Up only (no down on spot): shifts range one interval when price one grid above upper; needs ≥5 grids; optional trail limit; buys more base as it climbs.

## Bybit Futures Grid
- Long: "enter long positions upon creation at market price". Short: mirror. Neutral: NO initial position; longs below base price, shorts above.
- **Initial size formula UNDOCUMENTED** (genuine hole).
- USDT perp only. Arith+geo. Editable while running: investment + TP/SL only.
- Range exit: positions REMAIN OPEN, no new orders (idles WITH leveraged exposure). Auto-shutdown only on TP%, SL%, or liquidation. Manual termination: cancels orders AND closes positions at market — closing NOT optional.
- Trailing up AND down exist.

## Bybit Futures Martingale (no spot martingale product exists)
- Step measured FROM AVERAGE HOLDING COST (not last fill): next order price = avg cost × (1 − pct) for longs. ≠ Pionex (steps from last fill).
- "Position Multiplier" range **1 to 2**, applies to the last order **COST/margin** not quantity.
- "Max Addition per Round" = max adds per round (example 5; range unpublished).
- TP = "Profit Target per Round" as % of **TOTAL INVESTMENT** (not of avg entry). Closes all positions.
- "Enable Loop" optional → next round, else terminate. Bot-level SL on TotalPnL/Investment ratio; only SL editable after creation.
- USDT perp only, cross margin, ≤50x, ≤50 bots.

## Pionex Grid
- SEED: YES — "purchasing a specified percentage of the asset at current market price and placing sell orders above it". Third-party: 10 grids mid-range → buy 5 portions for the 5 upper rungs. Equal QUOTE VALUE per grid ($1000/grid) per third-party — differs from Bybit's equal-base-qty (official wording imprecise; flagged).
- Funding "USDT Only" or "Both" (contribute held base instead of market-buying).
- Params: lower/upper, grids, investment; arith+geo; AI Strategy (7-day backtest sets range/grids; what it optimises undocumented).
- Profit: "Grid Profit + Unrealized = Total"; buy pairs with sell one grid above.
- Trigger Price (delayed start); SL sells remaining spot; TP wording varies between two official pages (close+sell vs stop+cancel). Out of range: suspended, resumes. Manual close: SELLING OPTIONAL ("if you choose not to sell… it won't market sell").
- Max 200 grids (500 BTC/ETH). Spot; separate Futures Grid + Coin-M Grid products.

## Pionex Infinity Grid
- No upper bound; params: lowest price, profit per grid %, investment. Core invariant: CONSTANT POSITION VALUE ("keep it at $1000 whether it goes up or down" — sell just enough each step up). Implied geometric (never stated). Below lowest price: idles. NO trigger price, NO stop-loss (explicit). Re-invests some profit to cover fees.

## Pionex Martingale/DCA (spot; futures variant NOT confirmed to exist)
- Shares model: investment ÷ 2^n-ish shares; classic 1,1,2,4,8… **Volume Scale user-settable** (1.5 → 1, 1.5, 2.25…) — each order = multiple of PREVIOUS ORDER'S SIZE.
- DIY mode: per-safety-order share counts individually assignable.
- Price Scale: buy every X% drop measured FROM LAST FILL; AI presets 1%/5%. Step-scale multiplier (widening steps): not found — unknown.
- TP: % rebound from AVERAGE ENTRY COST → sells ALL (whole position). Auto-cycle mode → next round automatically.
- Max safety orders: NO published cap. Modes: Simple/Standard/Trailing (waits for bottom, buys after 0.5% rebound)/DIY; TBT/QFL entry signals; multi-coin composite.
- Stop-loss: not mentioned anywhere — absent or undocumented.

## Binance Spot Grid (contrast)
- Same seed pattern + a BASE-CURRENCY FEE RESERVE auto-refilled by market buys when below half. Warns actual investment may exceed entered amount.
- Auto Parameters from TA of symbol+period. Grid Profit = matched buy+sell pairs, fees pre-deducted.
- Out of range: suspended → resumes. SL price (must be below lower) / TP price (above upper) terminate. **Sell-on-stop is an opt-in checkbox at creation**, with liquidity escape hatch (may not sell). Only stop-trigger prices editable after creation.

## OKX Spot + Futures Grid (contrast; most configurable)
- Spot: same seed; fund quote/base/both; funds ISOLATED from trading account; TP sells all at market, manual stop = choice sell or keep. Trailing up/down.
- Futures: long/short/neutral; **"Open Position on Creation" toggle, ON by default — the only product that makes the seed optional**. Contract size per grid = f(investment excl reserved margin, leverage). Manual stop: close-all OR keep-positions. Reporting: "Grid Profit" vs "Unpaired PnL" (floating + FUNDING FEES + incomplete cycles — only product folding funding into the bucket). Broadly editable but edits re-initialize.

## Cross-product synthesis
- SEED universal on spot grids: market-buy base = per-grid amount × rungs above price, at creation. Variations: fund-with-held-base everywhere; Binance fee reserve; OKX futures opt-out toggle. Keep-vs-sell on stop optional everywhere on spot EXCEPT Bybit futures grid (always closes).
- NO product converts out-of-range into a stop by default — all idle/suspend/resume. (Matches v2's §5d idle.)
- Martingale: two semantic families — Pionex shares/volume-scale-of-previous, step from last fill, TP % of avg entry; Bybit margin-multiple (1-2× of previous COST), step from avg cost, TP % of total investment. "What the multiplier multiplies" and "what TP is a % of" differ per product — pin both in v3 vocabulary.
- Unresolved: Bybit futures grid seed formula; Pionex per-grid allocation (secondary source only); infinity spacing type; Pionex martingale max orders; Bybit spot grid editability.
