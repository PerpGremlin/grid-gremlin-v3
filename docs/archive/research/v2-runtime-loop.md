# Agent report: runtime loop (bot.py, apply.py, stops.py, wake.py, notify.py, main.py)

Repo read at HEAD 79c7da3, working tree clean. (Mainnet runs 76a702a per audit §4 — finding A below may or may not be in the deployed commit; check before panicking.)

## Stop types (config.py:18 STOP_TYPES = price, equity, adopt; dispatch stops.py:42,48,53)

- `price`: mark crosses operator-typed absolute price on losing side. mark<=value (long) / mark>=value (short). stops.py:42-43.
- `equity`: whole-account equity (not this bot's) falls to absolute level; side-agnostic. truth['equity'] injected bot.py:142. stops.py:48-52.
- `adopt`: fires when mark crosses the stop-loss price the operator placed on the venue's position. Takes NO value (config.py:437 gates value checks to price/equity). stops.py:53-57.
- All: no stop key → never; mark None → never ("absence is not a breach", spec_stops.py:88-90).
- Firing = _kill (bot.py:695-704): cancel own orders (prefix match), alive=False, kill event. NO position closed.

## The adopt dissection (all VERIFIED)

1. Config: `{"type":"adopt"}` passes validation with no other keys; legal on grid AND martingale.
2. Per cycle _read_truth injects t['position_stop'] = pos.get('stop_loss') (bot.py:144) — written exactly one place, read exactly one place (stops.py:54).
3. Source: Bybit derivs truth.py:59 (position stopLoss field). Bybit spot: key absent → adopt never fires on spot. Hyperliquid truth.py:105 hardcodes None ("phase 2 maps them") → **adopt structurally inert on all of mainnet** (mainnet is all-HL). Flat position → "" → falsy → inert while flat.
4. Position keyed by _pos_key (hedge mode reads own side's SL).
5. Evaluated once per cycle before fills/plan/apply (bot.py:181-183).
6. `if not sl: return False` → SL of exactly 0.0 treated as absent.
7. Fire → _kill; fleet loop skips forever (main.py:293), dropped from snapshots (main.py:228) → watchdog pages missing:<botid>.

State: reads config stop/side + truth mark/position_stop. Writes nothing while quiet; on fire alive=False + kill event. Stateless, level-triggered, re-evaluated every cycle.

Differences from price/equity: those are operator numbers in-process (die with the process); adopt's number lives on the exchange (protection survives process, reaction doesn't). adopt can't fire while flat. adopt is not a cause — the venue's engine independently closes the position; adopt just stops the bot laddering into a dying position. Only adopt is venue-conditional (no-op on spot and HL).

**Proposed name: `follow_position_sl`** (or mirror_venue_stop / stand_down_at_venue_sl). Avoid "adopt" (collides) and "obey/authority" (overstates).
Also: the enum itself is misnamed — `type` selects a watched quantity; adopt is the only verb. `{"stop": {"watch": "position_sl" | "mark_price" | "account_equity"}}` would be parallel.

### FOUR unrelated things called "adoption" (VERIFIED)
1. stop.type adopt — read-only mirror of venue stopLoss into a kill decision.
2. Restart order adoption — diff() matching resting orders by rung from orderLinkId (apply.py:11-19,47-71).
3. Martingale TP adoption — _tp_adopted/_tp_set (bot.py:106-108,447-455): first cycle with open position reads position['take_profit'], suppresses own TP write. Reads takeProfit and suppresses; #1 reads stopLoss and kills. Must NOT share a word in v3.
4. Docs' "adopting a position" — pointing a grid at a holding it didn't build (assumed_avg_entry/min_position_base/no_trade_pct family, "adoption-only" per spec_deadband.py:21,199,216-217).

## Module constants
- BACKOFF_CEILING 300s (bot.py:23); FLAP_LIMIT 3 (:26); FLAP_COOLDOWN 60s (:27); RECHURN_COOLDOWN 60s (:28-34); UNCOVERED_COOLDOWN 1800s (:35-39); CROSS_GUARD_BPS 5.0 (defined strategy/grid.py:24, imported) (:40-49); TRAIL_SNAP_HYST 0.05 fraction of range (:50-53); DIFF_QTY_RTOL 0.05 (:54-57); ERROR_CEILING 20 cycles (main.py:21,314-321); MMR_LADDER (main.py:23,302-312); EXIT_MARKUP_PCT 0.001 internal fee floor (strategy/grid.py:16-17); DEFAULT_WINDOW_PCT 0.05 (config.py:19).

## Identity / order-id scheme
- botid = 3-char category prefix + venue symbol + side initial, hyphens stripped (make_botid bot.py:60-61).
- Order id namespace: {botid}-{rung}-{gen}; names: link_id / orderLinkId / cloid (HL). bot.py:636-639; bybit client.py:395-399; HL venue.py:70-76.
- _gen: restart-unique suffix seeded int(time.time()), incremented per placement attempt (bot.py:85,640).
- _rung_of (apply.py:11-19): parse rung relative to own prefix; None for foreign/unparseable — the ownership guard.
- HL: gen % 36**4 packed to 4 base36 chars for 16-byte cloid; too-long links refused at fleet build (main.py:102-104).
- position_idx from (side, reduce_only); hedge 1/2, inverse 0, spot None→0 (_pos_key bot.py:130-133).
- One-bot-per-(category,symbol,positionIdx): bot_identity/check_fleet_unique (main.py:107,116).

## Bot per-instance state (ALL in-memory, none persisted; restart resets everything; exchange is the only durable state)
alive; _last_pos (fill detector + pos_stable baseline); _last_mark; _funding_time; _started; _backoff/_backoff_until/_backoff_emitted; _flap ((rung,side)→consecutive placed-not-resting); _cooldown ((rung,side)→epoch; written by BOTH flap and re-churn paths); _uncovered/_uncovered_at; _cb_noted; _spot_margin; kind; _entry (martingale round anchor); _tp_set; _round; _tp_adopted; _deadband_hwm (entry-side high-water ratchet, abs price); _sticky_ref; _trail/_marks/_upper/_lower/_resting_upper/_resting_lower. Fleet: mmr_seen, errors, notifier buffer, HL per-cycle snapshot cache.

## Cycle walkthrough (Bot.cycle bot.py:148-267)
0. Fleet: one read_wallet per venue shared by all bots (main.py:291); HL refreshes per-cycle snapshot cache used by amend_order.
1. alive gate. 2. _read_truth (+inject equity, position_stop). 3. record _last_mark. 4. one-shot start block (warn if spacing <1.5x no-place band; seed _last_pos so first cycle can't phantom-fill). 5. stop check → _kill+return. 6. read pos. 7. _cb_noted warn. 8. _detect_fills (pos delta → fill/exit events; no WS). 9. _detect_funding (nextFundingTime rollover, ≥$0.01). 10. martingale lifecycle (TP adoption; write TP once; round completion → repeat re-anchor or _kill). 11. build plan config: martingale overlay _entry; trail → _apply_trail (SMA, trail_target, trail event); grid → _apply_hysteresis (sticky ref plantruth) then _ratchet_deadband (rewrites no_trade_pct/entry_deadband_pct from _deadband_hwm, may go negative; passes unratcheted exit_deadband_pct). 12. plan() pure. 13. uncovered check (latch + 1800s). 14. window(desired, ref, place_within_pct) — ref not mark. 15. asymmetric diff: to_create from diff(live-windowed), to_cancel against FULL desired ladder (bot.py:239-260). 16. pos_stable = pos held still since last cycle. 17. _apply: amends (pair (rung,side,ro), price must match 1e-9, qty-only, gone/ambiguous skip, other → fallback cancel+create); cancels before creates (free margin first; voluntary entry cancel with cum_exec_qty==0 arms re-churn cooldown); margin backoff gate (cancels already ran, growth halted); clear stale _flap; creates (skip cooling, skip _would_cross, make_link, margin/ro_capacity/post_only_reject handling; pos_stable → flap counting). 18. _last_pos = pos.
Fleet after: snapshot every N, MMR ladder, error counter reset, break if none alive, waker.event.wait or sleep.

## Rate limits/cooldowns table
flap (rung,side) 60s after 3 strikes; re-churn (rung,side) 60s SAME DICT; margin backoff bot-wide 30s→300s doubling; margin anti-spam high-water; uncovered 1800s; funding dedup per rollover; telegram ≥3s + 429 penalty; WS reconnect 1→30s; fleet error ceiling 20; MMR once per rung crossed.

## Notify
Notifier (print sink) / TelegramNotifier (buffered, coalesced, re-queue on 429, MAX_BUFFER 2000 with dropped marker, oversize-line truncation guard notify.py:108-113). ORDER_KINDS placed/cancel/amend logged not shipped unless notify_orders. tag derived from live clients (venue+env), never a literal. 17 event kinds: fleet start skip placed cancel amend fill exit trail funding mmr margin backoff tp repeat kill warn ws dryrun (README:915-937). _describe: Side@price, 4 shown then +N more (bot.py:64-71).

## Error kinds (bot reacts to kinds, never venue codes)
gone (cancel silent, amend skip); ambiguous (never warn); margin (announce, backoff, early return); ro_capacity 110017 (silent continue, NOT flap-counted); post_only_reject HL (silent, flap handles); not_modified (TP treated as set); tp_through_market → _close_round_at (reduce-only marketable limit, bot.py:396-423).

## Churn guards in order (bot.py:547-559, README:271-297)
1 exit deadband/markup; 2 _would_cross (needs both quotes — backtester skips nothing); 3 flap cooldown; 4 re-churn cooldown (voluntary entry cancels only); 5 retired window hysteresis. Planner-side: _placeable_exits + truncation-tolerant diff (_matches: exits accept downward truncation 0<resting<=desired*(1+rtol); entries rel tol).

## NEW findings not in audit
A. **main.run() NameError: interval** — main.py:328,332 reference `interval`; param is poll_seconds (renamed, callee body missed). Outside the inner try/except → propagates after ONE cycle when cycles=None or >1. VERIFIED 3 ways (co_names, hasattr, git show HEAD). No spec drives run() past one cycle (spec_notify aborts in build_fleet) — fifth vacuous-coverage instance in the 3.8 family. NB repo HEAD 79c7da3 vs mainnet 76a702a — check which commit VPS runs.
B. README:1098-1100 + BOTS.md:230-233 claim "position→0 → bot kills itself" — path does not exist. _kill call sites: stop_hit and martingale-no-repeat only. Flat grid re-plans full entry ladder (correct, but docs promise the opposite).
C. README:1096-1097 claims adopt respects TP too — it reads only stop_loss. Hand-placed TP invisible to grid adopt.
D. desired order's link_id (strategy/grid.py:48-50, f'{botid}-{rung}', no gen) is dead — never placed, never read by diff; only consumer is dry_run's print (main.py:164) showing operators an id shape that never appears on-exchange.
E. window()'s param is named `mark` (window.py:10), every caller passes ref (sticky under hysteresis) — canonical implementation misnamed; adjacent to but distinct from audit 3.4.
F. Bot.cancel_all (bot.py:706-714): unpaginated (limit=50, no cursor follow — same bug spec_apply pins for read_orders, unfixed in sibling; --cleanup with >50 orders silently leaves remainder) AND raw Bybit camelCase keys (orderLinkId) vs normalised link_id used by _kill 12 lines above; HL hand-builds a Bybit-shaped dict just for this caller (venue.py:162-174). _kill and cancel_all = two impls of "cancel my orders".
G. _flap and _cooldown share one dict for two suppressions (book-race vs changed-mind), same 60s, indistinguishable in state/logs; only flap path emits an event. Narrower collision inside bot.py on top of audit 3.5.
H. _would_cross (bot.py:539-543) and _placeable_exits.blocked (grid.py:73-77) — identical guard formula duplicated character-for-character; constant unified 2026-07-30 but formula not; one branches on order side, other on bot side — equivalent only because exits oppose the bot, asserted nowhere.
I. stop.type values not parallel parts of speech — price/equity name watched quantities, adopt names a verb that doesn't occur; likely why audit couldn't name it.
J. Bot.notify is a noun assigned to self.notify — three names (notify/notifier/Notifier) for one thing.
K. "stop" means four things: config['stop'] kill rule; truth['position_stop'] venue SL price; client.set_trading_stop (only ever called with take_profit=!); stops.apply_stop (dead removed function). v3 must split "stand down" from "stop-loss".
