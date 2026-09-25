# Agent report: commercial martingale/DCA bots (web research, 2026-08-03)

## Genre verdict (the owner's ⚠ DECIDE)
**Dominant convention is unambiguous: each order = k × PREVIOUS order** (geometric via multiplier). Documented as previous-order multiplication by 3Commas, Bitget, OKX, KuCoin, Gate, Bybit, Binance, and Pionex Standard mode. The ONLY budget-normalised presentation is Pionex Simple/AI mode (shares 1,1,2,4,8,16,32 — itself a doubling ladder expressed as weights). Binance publishes the conversion: Total required = Base + SO×Σ multiplier^i.
Secondary conventions: (a) base order and first safety order sized independently (3Commas/OKX/Bitget/Binance); (b) step-scale multiplier compounds price spacing (3Commas invented; OKX/Binance/Bitget copied; Bybit/KuCoin/Gate fixed steps); (c) TP anchored to AVERAGE ENTRY everywhere except Bybit (% of total investment/ROI); (d) multiplier hard caps of 2 at Bybit and Gate.

## Futures scorecard
- Bybit: futures-ONLY martingale (no spot). Long+short, ≤50x, **Liq. Price displayed on bot details** (best liq-vs-ladder presentation), Enable Loop optional, profits NOT carried between rounds. TP = % of investment (unique). SL = % of max total loss. Step measured FROM AVG HOLDING COST (unique). Position Multiplier 1–2 applied to previous order COST.
- Bitget: spot + futures, ≤125x. Richest entry triggers: Immediate/Price/RSI/BOLL/**"Average price from previous cycle"** (anchor new round to last round's basis — unique). "Cycles" N or Infinite; **"Auto-renewal with profits"** = only explicit compounding-across-rounds toggle. TP ROI formula off avg cost + volume-reference switch (whole vs base order).
- KuCoin: spot + futures. Max Additions 1–25 ("once cap reached, bot stops purchasing and abandons the sequence" — bounded-loss framing). Leverage 10x (help) vs pair-max (blog) — CONFLICT. TP re-adjusts to avg entry per fill. No auto-restart documented. No SL parameter (advised only).
- OKX: Spot + Futures "DCA (Martingale)". Amount multiplier, price steps + steps multiplier (3Commas math). ≤100x nominal. Max safety orders margin-gated ("actual number may be determined by your margin"). Auto-cycles. NO published defaults/ranges at all; TP basis unstated.
- Gate: spot + futures. Amount Multiplier range 1–2. Fee-adjusted TP formula: TP = avg cost × (1 + ratio + 0.1%)/(1 − fee) — most explicit. SL = avg cost × (1 ± ratio). Max DCA orders (example 8).
- 3Commas (genre reference): base order + safety order + order size multiplier (martingale_volume_coefficient); deviation + deviation step multiplier; start conditions (signals); TP basis SWITCH (avg price default / base order); up to 4 partial TPs, trailing TP; SL from BASE order price, below last averaging order; cooldown between deals; Reinvest profit option; max averaging orders; **"Limit averaging orders placed on exchange" = windowing analog**. Futures ≤125x cross/isolated; leverage per-pair on Binance.
- Pionex: spot on web; **owner correction 2026-08-04 (D20): a futures martingale/DCA
  product exists but only in the mobile/tablet app**, which is why web sources missed it. Volume scale (Std) / share split (Simple); price scale from LAST FILL; TP % rebound from avg entry, sells all; auto-cycle; no SL documented; no max-orders cap published. Trailing mode (waits for bottom + 0.5% rebound); TBT/QFL signals; DIY per-order shares.
- Binance: **Spot DCA bot IS a martingale engine** (multiplier default 1 = flat DCA); futures suite has NO martingale. Price Deviation 0.1–15% + Deviation Multiplier default 1. TP off average, Fix or Trailing. Cooldown 60s default. Explicit required-capital geometric-series formula. Auto-Invest is time-based, irrelevant.

## Uniform gaps
No vendor documents hedge-mode or reduce-only TP flags. Liq-vs-ladder display only Bybit. Several help centers 403'd (Pionex zendesk, Gate, Bitget futures) — those details from search-indexed excerpts of official pages.

## Parameter-name table (for v3 vocabulary)
Size multiplier: Order size multiplier / Volume scale / Position Multiplier / Safety order size multiplier / Multiple for position increase / Amount multiplier / DCA Order Size Multiplier.
Step: Deviation / Price scale / Price Decrease-Increase % / Price drop steps / Percentage drop / Price steps / Price Deviation.
Step multiplier: Deviation step multiplier / Price steps multiplier / Safety order price interval multiplier / Price Deviation Multiplier.
TP basis: avg price default (3C switch to base order) / avg entry / % of investment (Bybit) / TP-ROI off avg cost (Bitget) / fee-adjusted avg cost (Gate).
