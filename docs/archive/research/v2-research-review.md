# Agent report: research corpus (PRIOR_ART.md + docs/research/*)

## Headline: the corpus never studied the alignment questions
research/README.md:23-30 — the five agents were pointed at: passivbot citation check + diff impl; nautilus adversarial on no-reconcile; freqtrade steelman polling; hummingbot connector + refresh churn; liquidation-and-risk MMR ladder trial. NO agent studied exit models, grid geometry, seeding, or martingale sizing. README:62-63: "Absence of a finding is not evidence of absence."

## 1. Exit models
- passivbot: netted in practice — ladder anchors to carried-forward position.price (entries.rs), entries/closes separate modules, close priority ranked by distance from position basis. OBSERVATION not a v2 decision.
- hummingbot: NO exit model to copy — cancel-all-or-keep-all, anonymous Proposal lists = the anti-pattern (REJECT).
- The corpus's exit-side prescription is about IDENTITY not pairing: diff by identity, fill on rung 7 → exactly one order placed (TAKE) — compatible with either model.
- The one netted-flavoured invariant: "sum(rung fills) == net position" tick check (freqtrade TAKE, required test invariant).
- "Paired profit" appears only as a backtester warning: touch-fill books a full fill and its paired profit — the matched-cell metric is the one naive fills inflate.
- NETTING TRAP: nautilus OmsType.NETTING = position-accounting netting (hedge-legs collapse), marked REJECT/bug-to-avoid — do NOT cite as support for the netted exit model.
- **Explicit netted-vs-cell decision: NOT IN CORPUS.** Lives only in BOTS.md:194-202 citing CHANGELOG/HANDOVER, not research. BOTS.md:198 "Hummingbot/infinity-grid model" claim UNSUPPORTED. BOTS.md:188 still states cell-paired wording six lines above the netted statement.
- Pionex/Bybit grid-product behaviour: NOT IN CORPUS (zero hits). BOTS.md:110-122 claims come from elsewhere.

## 2. Grid definitions
- passivbot grid MOVES (trailing EMA anchor; trailing_grid_v7.rs, trailing_martingale.rs). hummingbot ladders around moving mid. → v2's fixed {upper,lower,N} is a DIVERGENCE from all studied prior art (probably fine — but un-researched).
- TAKE principle: clear-and-re-derive is safe iff derivation depends only on carried state, never current bar (passivbot.md:248).
- freqtrade DIVERGE: grid danger states are inventory-shaped (ladder skew, inventory vs max position, distance-to-liq, funding bleed, price leaving the band) — closest support for boundary→idle.
- Anti-churn TAKEs: multiset diff + 2bps order_match_tolerance re-pair pass (pair NEAREST not greedy-first; name fractions _frac not _pct); cancels before creates with cancel-cap > create-cap; max order age expire-individually; re-anchoring prefix test (plan(truth[:T]) vs [:T+k]) = "single highest-value steal"; fail-closed truncating data provider; declared warmup requirement.

## 3. Start states
- SEED: TOTAL ABSENCE from corpus. No Pionex/Bybit start-behaviour research. Genuine gap — v3 must research or decide from scratch. Only adjacent: filter_by_min_effective_cost = coin-eligibility filter TAKE (budget can't fund one min entry → don't trade the coin; don't copy its live/backtest asymmetry).
- FLAT: only "unknown is not flat; unknown is don't trade" — gate trading on successful startup reconciliation, refuse otherwise (nautilus TAKE, settles DESIGN §7 Q1).
- ADOPT (rich): adopt unknown orders, never cancel-on-sight (freqtrade TAKE); self-heal within 2% band, refuse beyond (TAKE; inverse fees make naive dust logic wrong); adopted basis must match venue avg within 0.01% — solve fill price backwards, never invent (nautilus TAKE); content-addressed deterministic synthetic IDs (random UUIDs double-count every restart); deterministic orderLinkId makes adoption structural (kills the EXTERNAL-claims subsystem); REJECT fabricating phantom orders to force a position match (a bot with a position it cannot explain has a bug — halt and alert); order history capped 7 DAYS + lookback trap → cannot always reconstruct basis from fills, take venue avgPrice; refuse-on-ambiguity multi-currency.
- RESTART: in-flight as first-class state (sent-never-heard-back is neither intent nor truth); disappeared-order guardrail (uncancelled vanish → block new creates until all surfaces reconfirm at newer epoch; attribute by linkId not content); monotonic epoch + max() floor + execution barrier; reconnect = freeze submits + targeted resync (NO prior art — nautilus drifts, v2's pause instinct beats the field); five-layer race defense before acting on perceived mismatch (age skip, recent-activity skip, N consecutive misses, targeted confirm query, rate-limit); vanished order = counter then quarantine (4 misses), keep re-cancelling until terminal; dedup fills by venue execId across restarts.

## 4. Martingale
- Three mentions total. passivbot's martingale is TRAILING (anchored to moving ref) — v2's fixed-from-first_entry is a divergence, undiscussed. Triple-copied fill predicate DIVERGE (one definition). Funding is first-order and directionally biased AGAINST a martingale (accumulates counter-trend = the paying side); passivbot backtest models zero funding.
- Sizing semantics (multiple-of-previous vs weights vs double_down_factor): NOT IN CORPUS. BOTS.md:177-179 double_down_factor attribution UNSOURCED. BOTS.md:114-120 "emergent depth ~11%" UNSOURCED.
- Indirect support for total-normalised weights: liquidation-and-risk.md:81 "position sizing that makes liquidation impossible by construction… an arithmetic invariant you cannot violate" (multiple-of-previous needs an external terminator = the class argued against); all_or_none=True for rungs (shrunk rung breaks symmetry); cross-candidate collateral locking (list order = funding priority); single plan()-time placeable predicate; calc_min_entry_qty primitive.
- TP model: NOT IN CORPUS. Adjacent: /v5/position/trading-stop mechanics TAKE (tpslMode Partial on hedge = UNVERIFIED, load-bearing); Bybit DEMO HAS NO TP/SL (nautilus N12); liquidation CANCELS TP/SL orders (exchange-side TP not durable through liquidation).
- BOTS.md records the owner's own definition ("each step a multiple of the previous order's volume, 2x/1x/3x") then implements normalised level_weights WITHOUT reconciling the substitution.

## 5. Basis handling
- passivbot position model = (size, entry_price); marks exposure at ENTRY never mark = headline REJECT (measures commitment not danger; TAKE shape, mark at mark). nautilus computes maint margins at avg_px_open (same defect). hummingbot WS unrealized-pnl formula broken (use venue's own).
- Deadbands around basis: NOT IN CORPUS. Studied tolerance bands are anti-churn bands around desired prices — different thing; must not be cited as prior art for no_trade_pct/exit_markup family.
- Exits below basis: not addressed as design question. Adjacent negatives: gate_lossy_closes_by_peak_balance (refuses lossy closes; "opposite of liquidation prevention" REJECT — structurally same family as exit_against average); least_stuck_order trims healthy leg keeps toxic (REJECT).
- → NEITHER exit_against value has research support; cell-vs-average is entirely the owner's analysis; grid_profit_usd matched-cell metric is what touch-fill inflates.

## 6. Contradictions with BOTS/README (severity order)
1. Corpus #1 risk TAKE — SERVER-SIDE stop via /v5/position/trading-stop slTriggerBy=MarkPrice ("retail dead-man's switch, strictly dominates the local watchdog") — is UNIMPLEMENTED; apply_stop never called, removed. BOTS §6a frames whole-position exit as exchange-side; §6b admits true only for adopt + martingale TP.
2. BOTS "No account/MMR monitoring" over-reads: research killed the LADDER, prescribed 4 replacements — exposure cap Σnotional/equity as entry gate IN plan(); /v5/order/pre-check (preMmrE4, not for inverse cross); local MMR from tickers mark; ONE trip-wire at 25-30% MMR (stop opening + alert). None in BOTS.
3. "Hummingbot/infinity-grid model" unsupported.
4. double_down_factor + emergent-depth passivbot claims unsourced.
5. "Confirmed three ways" stop claim unsourced (freqtrade stops are actually the Protections plugins; open position immune to every protection; liquidation_buffer 0.05 fixed).
6. Pionex/Bybit-grid-product rationale rests on zero research.
7. Same-plan()-live-and-backtest supported BUT with unfulfilled condition: fix the fill model first (trade-through, not touch; model funding). v1's +54-vs-−151 may not have been only re-anchoring.
8. "Kill is not a risk control" (dead bot more dangerous than running one; kill only safe if exchange holds server-side stop) — bears on all stand-down paths.
9. PRIOR_ART's passivbot-corroborates-pushed-WS claim is a counterexample, must be deleted where it survives (required DESIGN edit; recheck v3 inherited framing).
10. exit_against presented as settled; corpus offers no prior art for either value.

## 7. Liquidation-and-risk essentials
- REPLACE the MMR ladder: it acts in a 0.33%-of-price window = 120-190x effective leverage region; none of 4 reference codebases has one; field pattern = exposure control before entry + one binary late stop.
- Numbers: MMR = m × eff_leverage, m=0.005 verified; 90% tier fires with 0.056% price room; at 25x fully deployed total adverse room 3.50%, ladder occupies last 9.5% of it; Bybit MMR Close capped ≤90% and liquidation takes precedence on surge; MMR never pushed on price moves (poll caps → ban risk); liquidation cancels ALL orders incl TP/SL, settles at bankruptcy price; 60% tier is dead code (IMR100% ⟺ MMR12.5%).
- Hedge defects: Bybit rejects its own MMR Close if it would raise account MMR (can unhedge and worsen); ADL targets the WINNING leg (PnL%×lev ranking) precisely during cascades → hedge is not the margin shelter it looks; server-side stop on hedged book must decide WHICH LEG; inverse aggregates into the same one-account-one-MMR queue.
- Watchdog "warn at 3, kill at 5" unsound ×3: one counter can't express 429/timeout/contract-violation; kill leaves orders+position live; already failed in production with the ladder (v1 swallowed errors; retCode 0 = accepted-not-done fed false success into the ladder).
- Equity floors: peak-relative and EMA-smoothed floors self-disable under stress (passivbot unstuck allowance leaky bucket; HSL min(raw, ema) suppresses panic during genuine gaps — "optimizing for backtest survivorship") → indirect support for ABSOLUTE equity level choice (no hidden baseline).
- passivbot backtest "liquidation" = equity ≤5% start, optimizer rejects on flag → systematic optimism at high leverage.
- UNVERIFIED load-bearing: position WS pushes on mark change?; MMR Close settable via API?; demo honours tpslMode Partial on hedge?; cross hedge IM formula (Bybit article 404s); 04:00-05:30 UTC repayment restriction (= step 2 of liquidation procedure); DCP "Ins clients" only; per-topic seq monotonicity.
