# Agent report: config layer (config.py, main.py, __main__.py, configs/, spec_configs.py)

## Key concepts + validation (highlights beyond other reports)
- venue: NOT validated by config.py (only in venues.venue_of → VenueConfigError, a ValueError, at fleet build). In COMMON_KEYS purely to survive _reject_unknown. Default bybit.
- category: config.py NEVER validates the value — only tests =='spot' in five places. "linnear" validates fine, fails later at resolve_instrument. Botid prefix = category[:3]. spot+short hard refusal.
- strategy: default grid. validate_martingale writes r['strategy']='martingale' back; validate_grid never writes 'grid' → every downstream reader repeats .get('strategy','grid') (M14).
- capital: number >0, no upper bound, no equity cross-check. investment in RENAMED (hard refusal, never alias).
- notional: ACCEPTED as input key then unconditionally overwritten by validator (M6) — silently discarded. grid.py:129-131 re-derives when absent (rule in two places).
- leverage: COMPLETELY UNVALIDATED (M3). 0 → silently 1 (or-1); -40 → negative notional; "40" → ValueError swallowed by build_fleet → row SKIPPED not refused. spot_leverage (less important) is range-checked [1,10]. main.py:105 asserts leverage from RAW row not validated cfg.
- rung_sizing equal/weighted; rung_weights required only when weighted, length==rungs, refused without weighted sizing.
- level_weights REQUIRED (unlike rung_weights), length==levels.
- rungs XOR spacing_pct (grid only); spacing supplied → rungs derived (ROUNDS) but spacing_pct kept verbatim → stale vs actual gaps; dry-run prints stale number (M9). Martingale has NO spacing alternative (levels required; spacing_pct not in MARTINGALE_KEYS).
- lower: TWO MEANINGS (M8) — grid bottom (upper>lower>0) vs martingale FAR END (above first_entry for a short; fleet.demo.json short has lower 1950.4 > first_entry 1912.2).
- place_within_pct: default 0.05, >0, NO upper bound (50 legal).
- split_deadband_rungs: [0, 0.5], grid only.
- arm_order/exit_against: optional, no default written back (code tests == 'furthest'/'rung'). Set by ZERO shipped configs. Also zero shipped: no_trade_pct, entry_deadband_pct, exit_markup_pct, exit_deadband_pct, stop (whole subsystem).
- assumed_avg_entry: refused unless spot; value above upper deliberately legal.
- Fraction intervals — FIVE conventions (M12): exit_markup_pct [0,1] closed; no_trade/entry_deadband/exit_deadband [0,1) half-open; take_profit_pct (0,1) open; split_deadband_rungs [0,0.5]; place_within_pct (0,∞).
- max_position_base: three-way — "unbounded" sentinel / number>0 / absent→derived full ladder. max>min cross-check only when BOTH explicit (M17: derived cap can be < min_position_base → zero-headroom dead grid, caught only for shipped configs by spec).
- spot_borrow: bool-coerced only inside the conditional (M16); README calls it spot_margin (D6).
- trail/stop: nested objects — UNKNOWN SUB-KEYS NOT REJECTED (M7). README's trail names (period/outer_lower/outer_upper) silently ignored → error names auto_trail.period which exists nowhere. stop {type adopt, value: X} — value silently ignored.
- repeat: coerced bool; refused with take_profit_price. Error messages still say "loop".
- take_profit_pct: (0,1) strict.
- Fleet keys (FLEET_KEYS main.py:27): bots, poll_seconds (NEVER type-validated), cancel_orders_on_exit (OR'd with --cleanup), notify_orders, _-comments. Bare top-level JSON list wrapped {'bots': data} BEFORE the fleet-key check → bypasses it (M15). Fleet unknown-key check re-implements _reject_unknown with cutoff 0.6 vs 0.7 and raises ValueError not ConfigError (M13).
- Exception types ×4 for config failures: ConfigError, VenueConfigError, ValueError, RuntimeError (spot_leverage disagreement, martingale-venue rule) (M10).
- Watchdog configs: NO validator at all — no key rejection, no types; tag required at one line, .get('tag','?') at another; positions{botid:{min,max}} KeyError if min/max missing.
- CLI: config positional, --dry-run --backtest --kline --bars --fee --no-funding --cycles --interval --cleanup --wake --snapshot --snapshot-every --allow-mainnet (per-venue gate).
- geometric_weights(): exported, documented in README §3, called by NO engine code.
- botid formula README omits the .replace('-','') strip (D20) — matters for hyphenated symbols and hand-matched watchdog keys.

## LIVE DEFECTS
- M1 = main.run NameError interval (confirms runtime agent finding A; tests survive because small `cycles` values skip the final sleep via the n<cycles guard).
- **M2 take_profit_price DEAD: config validates it, bot.py:392 reads .get('take_profit') (pre-rename). _round_tp → None → round laid with NO exchange-side exit — the exact failure BOTS.md §6b calls impossible. Affects fleet.mix/tight/tight3/stress.json (all historical test fleets, no systemd unit — but the key is dead for anyone). spec_martingale.py:229-235 asserts only bot death after round, never TP set from absolute key.**
- M5 RENAMED covers exactly ONE of ~21 keys renamed in the same commit (policy comment says "entries stay here for one release"). Old names → generic unknown-key; difflib hints misleading ('entry' matches nothing; 'weights' misses 0.7 cutoff vs rung_weights).
- M4 every validator error message names a dead key (full table: spacing_mode, sizing, window_pct, rung_hysteresis, N, spacing, weights, cost_basis, exit_basis, entry_fill, min_inventory, max_inventory [one message mixes both generations], spot_margin, auto_trail.*, steps, multipliers, entry, take_profit, loop).
- M11 exit_markup_pct default arg is dead code; explicit 0 floored back to 0.001 while sibling keys' docs say "0 disables".

## Dead/vestigial
take_profit_price (dead, M2); notional input (discarded); spacing_pct (stale after derive); arm_order/exit_against/deadband family/stop (set by nothing shipped); stop.value on adopt (ignored); geometric_weights (never called); trailed_bounds deadband (0.0 always); martingale lacks max_position_base AND min_position_base (audit noted max only) + split_deadband_rungs + spacing_pct → martingale has NO churn damping and inexpressible caps; venue/category in COMMON_KEYS unvalidated; fleet.mix/tight/tight3/stress historical, constrain schema via spec, all carry dead take_profit_price; PRE_MIGRATION_NOTIONAL/_marks/MIN_LOTS test-only; spec_configs duplicate import; spec_configs stale failure text ('poll_secondss' vs message 'intervall').

## Doc contradictions D1-D20 (beyond strategy agent's list; both agents overlap on examples-don't-validate)
D1 grid example geo/flat refused (×4 places). D2 martingale example investment refused (×7 places). D3 trail example wrong all three keys; shipped tight3 disagrees with doc. D4 exit_against cell. D5 arm_order near/far. D6 spot_margin vs spot_borrow. D7 exit_deadband_pct "not a config key" — it is, validated, honoured on ratchet early-return. D8 notional "not something you set" — settable, silently discarded. D9 notional=capital×leverage wrong for spot (page self-contradicts). D10 occupancy guess described as live AND deleted ~100 lines apart. D11 "kind:" headings (key is strategy). D12 --cycles description says "run exactly rungs poll cycles" — N→rungs substitution hit prose; rung_sizing table kept "investment ÷ N" — two halves of same rename disagree. D13 "0.1% floor regardless" false under rung. D14 entry_deadband_pct "true alias" — it's max(), not alias. D15 §8 "spot no leverage" contradicts §3 spot_borrow 10×. D16 §15 attributes fee floor to config key (it's the constant). D17 BOTS.md "README reference authoritative and kept current" — spec checks only key MENTIONED, not values legal. D18 BOTS.md §6b "reinvest machinery" — no reinvest exists anywhere (word survived one section past its own correction). D19 README measurement quotes dead deadband_pct. D20 botid formula omits hyphen-strip.
