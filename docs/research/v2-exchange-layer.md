# Agent report: exchange layer (adapters, venues, env, errors, wsclient, bybit/*, hyperliquid/*, watchdog, relay)

Base: /home/perpgremlin-/dev/projects/grid-gremlin-v2/

## Contract maths (adapters.py)
- _d (Decimal via str); _floor_to_step (step 0 = identity); _round_to_step (half-up); _fmt_step (plain decimal string at step precision).
- _Adapter: per-instrument contract maths from an exchange spec, never in config. category linear|inverse|spot|perp; supports_short; reports_avg_entry; settle_coin (spec, not parsed from symbol); one_way_mode; qty_step (aliases qtyStep/basePrecision/szDecimals→step); price_tick; min_qty; min_notional (None when venue has none).
- round_price (round to tick); round_qty (FLOOR to lot — never more than intended); fmt_price/fmt_qty; meets_minimum (qty floor AND notional floor); qty_from_notional (linear n/p; inverse n [1 contract=$1]; spot n/p) — the one place linear/inverse diverge; realised_pnl (settle coin); pnl_to_usd; position_idx from (side, reduce_only): hedge 1/2, inverse 0, spot None.
- LinearAdapter (USDT+USDC, settle as data) / InverseAdapter / SpotAdapter (long only, no idx, no reduceOnly, no avg entry). ADAPTERS registry.

## HL adapters
PRICE_SIG_FIGS 5; MAX_DECIMALS 6 (6−szDecimals); MIN_NOTIONAL_USD $10 const; _plain (strip trailing zeros); HLPerpAdapter (linear maths + HL rounding + one-way); sz_decimals; asset_id (universe index); max_leverage; _price_quantum (coarser of sig-fig grid and decimal cap, never coarser than 1).

## venues.py
VENUES ('bybit','hyperliquid'); DEFAULT_CATEGORY {'hyperliquid':'hl'} (also namespaces botid prefix); VenueConfigError; venue_of (default bybit); category_of (bybit rows MUST declare); make_client (read_only builds keyless reader where supported); clients_for (one client per venue, premade injection).

## env.py
load_env only: setdefault .env into os.environ (process env wins); whitespace-then-# inline comments (because a .env.example comment once resolved demo template to MAINNET — pinned spec_env.py:50-70); repo root by parents[2].
Env selection lives in clients: BYBIT_DEMO→demo else BYBIT_TESTNET→testnet else MAINNET; HL_TESTNET→testnet else MAINNET (no demo tier). Write gate per venue AT THE CLI only: __main__.py:78-86 any client env==mainnet without --allow-mainnet → REFUSING exit 2; --dry-run/--backtest bypass (read_only). Second independent gate for HL smoke test.

## errors.py
KINDS: gone, not_modified, cannot_modify, ro_capacity, margin, rate_limit, post_only_reject, tp_through_market, other. VenueError(msg, kind, ambiguous) — ambiguous = "write MAY have landed", never a rejection. InstrumentError = setup-time refusal.
Handling: NO kind kills. gone→idempotent success; not_modified→done; cannot_modify→SettingsError→ROW skipped at build (not fleet); ro_capacity→silent retry, excluded from flap; margin→backoff 30s→300s; rate_limit→client sleeps to window reset, re-raises; post_only_reject→silent, flap cools; tp_through_market→_close_round_at; other→warn+retry. ambiguous=True suppresses warning entirely, defers to next truth read. In-client: Bybit 10002 clock resync retry once; HL 429 one 2s retry on /info NOT /exchange; HL 5xx/network-after-send → ambiguous.

## Bybit client.py
_BASE_URLS demo/testnet/mainnet; AMBIGUOUS_CODES (14); NOT_MODIFIED {110025,110043,34040}; CANNOT_MODIFY {110024,110028}; ORDER_GONE {110001,170213}; RO_CAPACITY {110017}; INSUFFICIENT_MARGIN (8 incl 500-order account cap 170810); RATE_LIMIT {10006,10018,10429,429}; RATE_LIMIT_FLOOR 3 (proactive glide via X-Bapi-Limit-Status; _wait_for_reset bounded 0-5s server-relative). BybitError retCode→kind. Client: _detect_env; recv_window 15000 (stored as STRING, M24); _time_offset/_sync_time (resync once on 10002); _sign HMAC-SHA256 ts+key+recvWindow+payload; public reads instruments_info/tickers/kline/klines/funding_history; private wallet_balance(UNIFIED)/position_list/open_orders (ONE page, cursor param); set_spot_leverage (account-level); set_leverage; switch_position_mode (0 one-way / 3 hedge); place_order (is_leverage = SPOT-only per-order borrow flag); cancel_order; amend_order (keeps queue priority on same-price qty decrease); set_trading_stop (tpslMode Full); MAX_LINK_LEN 36. Venue surface: make_link, read_wallet, read_symbol_truth, ensure_leverage, ensure_position_mode, resolve_instrument + writes (pinned spec_venues.py:61-67).

## Bybit truth.py
read_wallet (equity/available/mm_rate/im_rate/maint_margin/coins; EMPTY-ACCOUNT EARLY RETURN emits only {equity,available,coins} — two shapes, M15). read_positions keyed by positionIdx. _MAX_ORDER_PAGES 500 — RAISES on hitting it (runaway backstop not truncation, M27). _all_open_orders follows nextPageCursor, raises rather than partial book. read_orders normalises. read_spot_position = base-coin wallet balance keyed 0, avg_entry always 0.0, stop_loss/take_profit KEYS ABSENT (M14). read_symbol_truth: mark(markPrice else lastPrice)/bid/ask/ref=(bid+ask)/2 else mark/funding/orders/positions.

## Bybit instruments/settings
parse_instrument → spec dict; adapter_for; resolve (refuse unknown/non-trading/dated; assert qty_step/price_tick/min_qty). HEDGE_MODE=3; SettingsError; ensure_leverage → set|already|n/a; ensure_position_mode → n/a|one-way|set-hedge|already-hedge (blocked switch → refuse loudly).

## HL client/exchange/signing
InfoClient (mainnet/testnet only; RETRY_429_WAIT 2.0; HLError classifies from message TEXT; _user refuses nameless account; meta/meta_and_asset_ctxs/l2_book (SERVER clock)/funding_history (RAW json — different return type than bybit's sorted tuples, dup 17)/candles/clearinghouse_state/frontend_open_orders/user_abstraction/spot_clearinghouse_state).
ExchangeClient: wallet=priv_to_address (signer may differ from traded account); _nonce strictly-increasing ms; _post_action (5xx/network-after-send → ambiguous); _statuses → resting|filled|ok|error; _order_wire a,b,p,s,r,t,c refuses floats by type check; place_order = post-only Alo; cancel_order by cloid preferred (already-gone idempotent ×3 implementations, dup 10); amend_order = batchModify with FULL new body; update_leverage.
signing.py: pure-python keccak256, msgpack subset (floats REFUSED), secp256k1 Jacobian, RFC6979, low-s ECDSA with recovery id, priv_to_address, EIP-712 (Exchange/1/chainId 1337), action_hash = keccak(msgpack(action)+nonce+vault flag) ("connectionId"), sign_l1_action (source 'a' mainnet 'b' testnet), CLOID_BYTES 16, link_to_cloid/cloid_to_link ASCII verbatim null-padded REVERSIBLE no hashing (HYPERLIQUID.md:130 says "hash" — M37).

## HL instruments/truth/venue
parse_instrument; resolve (refuse unknown+delisted). UNIFIED_MODES (collateral in spot clearinghouse); HOUR_MS; read_wallet (mode-aware: classic accountValue/withdrawable; unified perp+spot arithmetic; mm_rate/im_rate COMPUTED not venue-supplied); read_positions (szi sign → side, keyed 0); read_orders (origSz/sz → qty/cum_exec derived; isTrigger filtered; cloid decoded); _ctx_for POSITIONAL zip (documented wrong for spot in HYPERLIQUID.md:242-246, unfixed — M34); read_symbol_truth (l2_book is the ONLY per-symbol call).
HLVenueClient (venue.py): facade wearing Bybit surface. _b36/GEN_CHARS 4 (~19-day wrap); _assets symbol→index cache; _cache {state,orders,ctxs} per-cycle, REFRESHED BY read_wallet (cache-mutating read, M21 — read_symbol_truth silently calls it if missing, 3-4 extra API calls); _mode detected once; amend_order recovers body from cycle snapshot, miss → kind gone; open_orders hand-builds Bybit-shaped {'list':[...]} FRESH read for shutdown path; set_trading_stop RAISES unconditionally (surface presence ≠ capability, M19); place_order accepts and drops position_idx/is_leverage (M18); read_symbol_truth ignores 3 of 4 params (M17); make_link ≤16B REFUSES oversize at fleet build.

## Truth contract (NO class, NO schema — two independent bare dicts pinned only by spec_hyperliquid.py:176-227)
T1 symbol truth: symbol, category (bybit passes arg; HL HARDCODES 'perp' while venues says 'hl' — M10 three values one bot), mark (HL never falls back), bid/ask (HL costs extra l2 call), ref (identical formula DUPLICATED verbatim), funding_rate (**UNIT DIFFERS: Bybit 8-hourly vs HL HOURLY, same name, no marker; _detect_funding multiplies identically — M16**), next_funding_time (bybit venue-supplied; HL COMPUTED from server clock), orders, positions.
Injected downstream by Bot._read_truth: equity (from wallet), position_stop (from positions[key].stop_loss).
T2 order dict 11 keys both venues: order_id, link_id, side (HL 'B'→Buy else Sell), price, qty (Bybit ORIGINAL vs HL origSz — HL sz is REMAINDER), cum_exec_qty (derived on HL), reduce_only, status (HL synthesises New|PartiallyFilled only), position_idx (HL hardcoded 0), order_type, updated_time. Trigger orders excluded both venues.
T3 position dict THREE shapes: bybit deriv (full); bybit spot (avg_entry 0.0, stop_loss/take_profit ABSENT); HL (take_profit ABSENT, stop_loss always None).
T4 wallet: equity/available/mm_rate/im_rate/maint_margin/coins (+mode HL only; HL coins has 2 extra keys; bybit empty-account path drops 3 fields).

## Layering: four names, THREE concepts
- "exchange" = package root AND HL write module (two unrelated uses, M6/M7 docstrings lie).
- "venue" = config name + method surface; never an object on Bybit side.
- "client" = the object speaking the surface; Bybit Client IS the HTTP client (1 layer); HL is facade HLVenueClient → ExchangeClient/InfoClient (2 layers, facade lives in venue.py while wrapped things live in client.py/exchange.py).
- "adapter" = genuinely separate (pure contract maths).
venue ≈ client = two names one concept.
Order placement: Bybit 3 hops; HL 6 hops (wire order → sign_l1_action → msgpack+keccak+ecdsa). Truth read: Bybit 1 account call + 3/symbol (tickers, orders×pages, positions; spot reuses wallet = 0 extra); HL 3-4 shared calls at read_wallet + 1 l2_book/symbol.

## Duplicates bybit/ vs hyperliquid/ (24, all VERIFIED)
_f coercer byte-identical; read_wallet/read_positions/read_orders/read_symbol_truth same contracts written twice; ref formula verbatim; parse_instrument/resolve; _fmt_step vs _plain (different trailing-zero policy); error classification twice (deliberate per errors.py:6-10); "already gone = success" ×3 on HL side; _detect_env; _BASE_URLS; make_link (36B plain vs 16B b36); open_orders {'list':…} REST-native vs hand-synthesised; rate limiting (glide-under-cap vs one-retry); funding_history same name DIFFERENT return type; kline/klines/candles three names; .env parsing ×3 (env.py regex, watchdog split, relay regex); Telegram send ×3 (notify, watchdog, relay); ambiguity marking; position_idx-returns-0 identical one-liners ×2; one_way_mode True ×3; linear P&L correctly shared (the one good case).

## Name-vs-behaviour (M1-M37 highlights)
- M1 Client.kline/klines: body reads `interval`, param renamed poll_seconds → NameError on ANY call → **whole backtester dead** (main.py:188).
- M2 main.run: loop reads `interval` at :328,:332, param is poll_seconds → **NameError end of first cycle, live fleet loop broken**. (= runtime agent's finding A.)
- M3 HL candles sends 'poll_seconds' as the JSON WIRE KEY (should be interval).
- M4 HL spike runner --grid: args.place_within_pct vs dest window_pct → AttributeError.
- M5 "kind" renamed to "strategy" in PROSE only (3 docstrings; attr is kind everywhere).
- M10 category = 'hl' (identity) vs 'perp' (adapter+truth) for one HL bot.
- M11 HL price_tick documented as NOT the binding rule (round_price ignores it).
- M12 HL min_qty IS qty_step (one number two names).
- M13 min_notional = 4 upstream identities (minNotionalValue/minOrderAmt/$10 const/None).
- M20 open_orders = "one page ≤50" on Bybit vs "all" on HL; Bot.cancel_all doesn't follow cursor → shutdown can leave orders resting.
- M22 make_client read_only IGNORED for bybit → --dry-run still requires keys.
- M23 errors.KINDS over-promises (bybit never emits post_only_reject; HL never emits tp_through_market/not_modified/cannot_modify).
- M25 "stop" doesn't close the position (self-documented; name reads as exit).
- M26 wsclient at venue-neutral root but Bybit-private-stream-specific.
- M28 bybit/truth.py:71-73 comment describes the paging bug in present tense about the fixed function.
- M29 unit_failed = "KNOWN failed" (False on any uncertainty).
- M30 peak_equity(prev, None) → prev or 0.0 — falsy sentinel disables drawdown check.
- M31 evaluate() mixes breaches and liveness (missing:{botid}) in one channel.
- M32 spot borrowing: spot_borrow/is_leverage/isLeverage/spot_leverage — 4 names 2 concepts.
- M33 429/10006 in BOTH rate-limit and ambiguous sets (pre-reject ≠ ambiguous; pinned).
- M35 CROSS_GUARD_BPS (venue/book concern) defined in strategy/grid.py.
- M36 HYPERLIQUID.md says "nothing built yet" below a phase list saying 1-5 DONE.

## Watchdog
Keys: tag, snapshot, state, staleness_seconds, mm_rate_max, equity_min, equity_drawdown_max, re_alert_seconds, suppress_when_failed, positions{botid:{min,max}}.
evaluate() breaches: nosnap, stale, mmr, equity, drawdown (vs carried peak), missing:{botid} (liveness), pos:{botid}. NEVER kills, never trades — pages Telegram; decide() = page new / recovered / reminder ≥ re_alert_seconds; stands down when unit KNOWN-failed; SENDS BEFORE PERSISTING state (failed page re-pages).
Overlaps: equity_min ≡ stop type 'equity' unit+meaning (engine kills bot, watchdog pages human) = audit 3.6; mm_rate_max overlaps MMR_LADDER (observes only); positions{min,max} overlaps max_position_base (spec pins ceiling between cap and 1.5× — detects the cap itself failing). Staleness has no engine analogue; engine's only self-stop is ERROR_CEILING 20.

## wsclient/wake
WakeSignal only consumer. wss private stream, auth HMAC verify-ack (rejected auth raises), subscribe order+execution; any matching frame sets a threading.Event — NO payload parsed into state. No staleness detector: settimeout(20)→ping; CLOSE→reconnect 1→30s backoff. Fail-safe: dead socket degrades to polling; truth never sourced from WS. HL has NO websocket path.

## Startup adoption/reconciliation — NO routine, continuity emergent
1. Orders: diff() keeps resting orders matching plan via {botid}- prefix rung parse; foreign orders never cancel candidates; duplicates self-heal (keep one, cancel rest).
2. Positions: implicit — plan() pure over truth carrying live size/avg.
3. Martingale TP adoption: one-shot _tp_adopted (cannot function on HL — no take_profit in truth; consistent with martingale asserted USDT-linear-only at build main.py:98-100).
4. stop adopt reads position_stop.
5. ensure_leverage/position_mode: ask-and-correct ONCE at build.
6. HL amend recovers body from cycle snapshot, miss → gone → recreate.
7. assumed_avg_entry: spot-only config fallback, venue overrides, one-shot warn.
8. GAP (INFER): nothing reconciles orphaned orders left by a bot REMOVED from the fleet — no botid claims them, they rest forever.

## Relay (scripts/relay.py)
4th dotenv parser; accepted() owner-only fail-closed; workstation_live heartbeat ALIVE_MAX 180s; route vc/workstation with /vc override; append_inbox fsync BEFORE ack; ask_claude sandboxed headless; persist-then-ack ordering.
