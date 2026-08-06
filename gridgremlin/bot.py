# The loop with its guards (SPEC E2, E3, W1, B3-B7, T2).
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .exchange.errors import VenueError
from .ladder import (anchor_from_rung, grid_rungs, guard_band, lot,
                     min_gap, plan_grid, plan_martingale,
                     sellable_base, split)
from .window import window

FLAT_CONFIRMATIONS = 3  # E9: consecutive flat reads before standing down
FLAP_LIMIT = 3          # B5: strikes before a (rung, side) cools
FLAP_COOLDOWN = 60.0
BACKOFF_BASE = 30.0     # B7: margin backoff, doubling to the ceiling
BACKOFF_CEILING = 300.0
HISTORY_WINDOW_DAYS = 30    # M12/M13: the venue-practical fills lookback


class Bot:
    # E3/S6: the reset-on-restart list, complete and asserted by spec —
    # _last_pos (fill baseline, re-seeded first cycle), _gen (restart-unique),
    # _held_ref (re-anchors), _placed_last/_flap/_cooldown (churn guards),
    # _backoff*/_exit_links_last/_uncovered_warned/_anomaly_warned (latches).
    # Everything else the bot knows comes from the venue each cycle.

    def __init__(self, cfg, adapter, client, notifier, gen_seed, clock=None,
                 tombstones=None):
        self.cfg = cfg
        self.adapter = adapter
        self.client = client
        from .config import VENUE_ICONS
        from .events import VenueNotifier
        self.notify = VenueNotifier(
            notifier, VENUE_ICONS.get(cfg.get('venue'), ''))
        self.botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        self._gen = gen_seed
        self._now = clock or time.time
        self._last_pos = None
        self._placed_last = set()      # (rung, side) placed on the prior cycle
        self._flap = {}                # B5: (rung, side) -> strike count
        self._cooldown = {}            # B6: (rung, side) -> (until, cause)
        self._backoff = 0.0            # B7
        self._backoff_until = 0.0
        self._backoff_emitted = 0.0
        self._entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'
        self._exit_side = 'Sell' if cfg['side'] == 'long' else 'Buy'
        self._held_ref = None          # B2
        self._min_gap = (min_gap(grid_rungs(cfg, adapter))
                         if cfg['strategy'] == 'grid' else 0.0)   # M8: no lattice
        self.alive = True
        self._exit_links_last = set()  # S7: the ownership discriminator
        self._uncovered_warned = False
        self._anomaly_warned = False
        self._anchor = None            # M: the round's base price
        self._borrow = bool(cfg.get('spot_borrow'))    # D24
        self.tombs = tombstones        # X7: the prevents-restart half of D1
        self._round = 0
        self._scale = None             # M12: reinvest factor, venue-derived
        self._cool_until = None        # M13: venue-anchored, recomputed on need
        self._unplaceable_warned = False
        self._history_capped_warned = False
        self._flat_streak = 0          # E9: confirmations of 'flat'
        self._round_hwm = None         # M10: best mark seen this round
        self._basis_cache = None       # G15: (held, basis) from fills

    def _kill(self, truth, reason):
        """D1/S7: cancel every owned order, stand down, never restart. X4:
        the event states what still rests. X7: tombstone FIRST."""
        if self.tombs:
            try:
                self.tombs.add(self.botid, reason)
            except OSError as e:
                self.notify.event('warn', self.botid,
                                  f'tombstone write FAILED ({e}) — killing '
                                  'anyway; this bot may revive on restart')
        n = 0
        for o in truth['orders']:
            if rung_of(o['link_id'], self.botid) is not None:
                try:
                    self.client.cancel_order(self.cfg['market_type'],
                                             self.cfg['symbol'], o['order_id'])
                    n += 1
                except VenueError:
                    pass
        self.alive = False
        self.notify.event('kill', self.botid,
                          f'{reason} — cancelled {n} owned orders; nothing '
                          'owned rests; position flat')

    def _stop_hit(self, truth, equity):
        """X2: the rule names what it watches. Absence is never a breach."""
        stop = self.cfg.get('stop')
        mark = truth['mark']
        if not stop or mark is None:
            return None
        watch, long = stop['watch'], self.cfg['side'] == 'long'
        if watch == 'mark_price':
            hit = mark <= stop['level'] if long else mark >= stop['level']
            return f"mark_price {stop['level']:.10g}" if hit else None
        if watch == 'account_equity':
            if equity is not None and equity <= stop['level']:
                return f"account_equity {stop['level']:.10g}"
            return None
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        sl = truth['positions'].get(idx, {}).get('stop_loss')
        if not sl:
            return None
        hit = mark <= sl if long else mark >= sl
        return f'position_sl {sl:.10g} (yours, on the venue)' if hit else None

    def _flatten_scope(self, held):
        """X6 (D2): grid inventory only — the floor core survives. A
        martingale has no floor; its scope is the whole position."""
        if self.cfg['strategy'] == 'martingale':
            return abs(held)
        return sellable_base(self.cfg, self.adapter, held)

    def _execute_stop(self, truth, held, reason):
        """X1 (D1): flatten, cancel, kill, never restart. X4: the event
        states what still rests. X5: owned orders only, from paginated truth."""
        cfg, adapter = self.cfg, self.adapter
        if self.tombs:                 # X7: durable BEFORE the flatten — a
            try:                       # crash mid-stop stays dead
                self.tombs.add(self.botid, reason)
            except OSError as e:       # a broken disk must never block the
                self.notify.event('warn', self.botid,   # flatten itself (M3)
                                  f'tombstone write FAILED ({e}) — stopping '
                                  'anyway; this bot may revive on restart')
        qty = self._flatten_scope(held)
        if qty > 0:
            self._gen += 1
            try:
                self.client.place_market(
                    cfg['market_type'], cfg['symbol'], self._exit_side,
                    adapter.fmt_qty(qty),
                    adapter.position_idx(self._exit_side, True) or 0,
                    reduce_only=True, link_id=self._make_link(0),
                    borrow=self._borrow)
            except (VenueError, OSError) as e:      # raw OSError too (M2)
                self.notify.event('warn', self.botid, f'flatten: {e}')
        floor = abs(held) - qty
        try:                           # X4 honestly: re-read, never assume the
            after = self.client.read_symbol_truth(     # flatten fully filled
                cfg['market_type'], cfg['symbol'],
                cfg.get('funding_interval_minutes', 480.0))
            idx_now = adapter.position_idx(self._entry_side, False) or 0
            left = (after['positions'].get(idx_now) or {}).get('size', 0.0)
        except Exception:                                    # noqa: BLE001
            left = None
        if left is None:
            residue = f'flatten SUBMITTED for {qty:.10g}; venue unreadable to confirm'
        elif left > floor + 1e-12:
            residue = (f'position {left:.10g} STILL OPEN (flatten partial?) — '
                       'look at the venue')
        elif floor > 1e-12:
            residue = f'floor core {floor:.10g} REMAINS, unprotected'
        else:
            residue = 'position flat'
        n = 0
        for o in truth['orders']:
            if rung_of(o['link_id'], self.botid) is not None:
                try:
                    self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                             o['order_id'])
                    n += 1
                except VenueError:
                    pass
        self.alive = False
        self.notify.event('kill', self.botid,
                          f'stop fired ({reason}): flattened {qty:.10g} at '
                          f'market; cancelled {n} owned orders; nothing owned '
                          f'rests; {residue}')

    def _maintain_server_stop(self, truth, held):
        """X3: the venue holds the stop, sized to the grid's inventory —
        level-triggered every cycle, so growth re-sizes it."""
        stop = self.cfg.get('stop')
        if not (stop and stop.get('server_side') and held and abs(held) > 0):
            return
        qty = self._flatten_scope(held)
        if qty <= 0:
            return
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        venue_sl = truth['positions'].get(idx, {}).get('stop_loss')
        want = self.adapter.round_price(stop['level'])
        partial = self._flatten_scope(held) < abs(held)
        if venue_sl is not None and abs(venue_sl - want) < 1e-9:
            if not partial:
                return                            # the venue already agrees
            # partial mode: the level agreeing says nothing about the SIZE —
            # the audit's H2: growth must re-size the venue's conditional.
            # Partial-mode set_trading_stop STACKS a new conditional per
            # call, so stale ones are cancelled before the new set.
            book = getattr(self.client, 'stop_orders', None)
            if book is not None:
                mine = [o for o in book(self.cfg['market_type'],
                                        self.cfg['symbol'])
                        if 'StopLoss' in (o.get('stopOrderType') or '')
                        and int(o.get('positionIdx') or 0) == idx]
                have = sum(float(o.get('qty') or 0) for o in mine)
                if abs(have - qty) <= max(qty * 0.001, 1e-12):
                    return                        # level AND size agree
                for o in mine:
                    try:
                        self.client.cancel_order(self.cfg['market_type'],
                                                 self.cfg['symbol'],
                                                 o['orderId'])
                    except VenueError as e:
                        if e.kind != 'gone':
                            raise
        try:
            self.client.set_trading_stop(
                self.cfg['market_type'], self.cfg['symbol'], idx,
                stop_loss=self.adapter.fmt_price(want),
                sl_size=self.adapter.fmt_qty(qty) if partial else None)
            self.notify.event('tp', self.botid,
                              f'server-side stop resting at {want:.10g} '
                              f'for {qty:.10g} — survives this process')
        except VenueError as e:
            self.notify.event('warn', self.botid, f'server stop: {e}')

    def _round_target(self, basis):
        """M4: from average entry, recomputed as fills deepen."""
        pct = self.cfg['take_profit_avg_pct']
        raw = basis * (1.0 + pct) if self.cfg['side'] == 'long' \
            else basis * (1.0 - pct)
        return self.adapter.round_price(raw)

    def _own_fills(self):
        """M12/M13: this bot's venue fills over the last HISTORY_WINDOW_DAYS,
        link-attributed — the exchange is the state, so scale and cooldown
        survive restarts. Bounded: an epoch-0 pull was ~3,000 requests (the
        audit's H1); 30 days is five."""
        hist = getattr(self.client, 'fills_history', None)
        if hist is None:
            return []
        now_ms = int(self._now() * 1000)
        since_ms = now_ms - HISTORY_WINDOW_DAYS * 86_400_000
        fills = hist(self.cfg['market_type'], self.cfg['symbol'], since_ms,
                     now_ms)
        if len(fills) >= 2000 and not self._history_capped_warned:
            self._history_capped_warned = True
            self.notify.event('warn', self.botid,
                              'fill history hit the venue cap — reinvest/'
                              'cooldown are reading a truncated window')
        return [f for f in fills
                if rung_of(f['link_id'], self.botid) is not None]

    def _derive_basis(self, held):
        """G15: a venue that reports no average entry (spot: the position IS
        a wallet balance) leaves the exit floor with nothing to clear, so
        exits may rest at the very price the inventory was bought at — the
        grid churns at zero spread and pays fees both ways (measured live
        2026-08-06: 17 LTC round trips, every buy and sell at one price).
        The venue still knows: its own fill history reconstructs the cost."""
        if not held or self.adapter.reports_avg_entry:
            return None
        cached = self._basis_cache
        if cached and abs(cached[0] - held) < 1e-12:
            return cached[1]
        try:
            fills = self._own_fills()
        except (VenueError, OSError):
            return cached[1] if cached else None
        if not fills:
            return None
        from .report import apply_fill, new_book
        book = new_book()
        for f in sorted(fills, key=lambda f: f['time_ms']):
            apply_fill(book, f['side'], f['price'], f['qty'], f['fee'])
        basis = book['avg_cost'] if abs(book['position']) > 1e-12 else None
        self._basis_cache = (held, basis)
        if basis:
            self.notify.event('net', self.botid,
                              f'basis derived from venue fills: {basis:.10g} '
                              '(this venue reports none — G15)')
        return basis

    def _how_round_ended(self):
        """M14: read the venue's own account of the closing fill — our exit
        (link or hosted TP), a liquidation, or an outside hand. None means
        the venue could not tell us, and silence is never evidence."""
        try:
            fills = self._own_fills_all()
        except (VenueError, OSError):
            return None
        if not fills:
            return None
        last = max(fills, key=lambda f: f['time_ms'])
        kind = str(last.get('venue_kind') or '')
        if 'liquidation' in kind.lower() or 'adl' in kind.lower():
            return 'liquidation'
        if rung_of(last['link_id'], self.botid) is not None:
            return 'exit'
        if last.get('venue_closed'):
            return 'exit'                      # the venue's hosted TP/SL
        return 'an outside close'

    def _own_fills_all(self):
        """Every recent fill on OUR symbol — including ones with no link
        (a liquidation carries none), which _own_fills deliberately drops."""
        hist = getattr(self.client, 'fills_history', None)
        if hist is None:
            return []
        now_ms = int(self._now() * 1000)
        return hist(self.cfg['market_type'], self.cfg['symbol'],
                    now_ms - 2 * 86_400_000, now_ms)

    def _reinvest_scale(self, fills):
        """M12: 1 + lifetime realized-net / capital, floored at 0, CAPPED at
        1.2 — the watchdog ceiling sits at cap x1.2 (F2), so auto-compound
        never outgrows its watcher; beyond +20% the owner raises capital in
        config, ceiling reviewed together (D26)."""
        from .report import apply_fill, new_book
        book = new_book()
        inverse = self.cfg['market_type'] == 'inverse'
        for f in sorted(fills, key=lambda f: f['time_ms']):
            apply_fill(book, f['side'], f['price'], f['qty'], f['fee'],
                       inverse=inverse)
        from .report import window_truncated
        if window_truncated(book, self.cfg['side']):
            # R7's honesty applied here: the window opened mid-round, so the
            # ledger holds a phantom. Scaling on it is worse than not scaling.
            self.notify.event('warn', self.botid,
                              'reinvest: the fill window opened mid-round — '
                              'holding sizes at 1.0 this round (M12)')
            return 1.0
        net = book['realized'] - book['fees']
        if inverse:
            net = self.adapter.pnl_to_usd(net, fills[-1]['price']) if fills \
                else 0.0
        return min(max(0.0, 1.0 + net / self.cfg['capital']), 1.2)

    def _round_targets(self, basis, held, mark=None, guard=0.0):
        """M4/D23: targets from average entry; tranches share ONE position.
        A tranche the mark has already PASSED is done (filled, or owed at
        better-than-target) — it is filtered out and the remaining shares
        renormalise over what is still held, so a filled tranche is never
        re-placed below mark (the venue refuses those, correctly). An empty
        return means every target is met: the caller closes the remainder."""
        tranches = self.cfg.get('take_profit_tranches')
        if not tranches:
            return [(self._round_target(basis), abs(held))]
        adapter, long = self.adapter, self.cfg['side'] == 'long'
        sign = 1.0 if long else -1.0
        priced = [(adapter.round_price(basis * (1.0 + sign * t['at_avg_pct'])),
                   t['share']) for t in tranches]
        if mark is not None:
            # M10: "passed" must be MONOTONE within a round — measured
            # against the best mark the round has seen, not the current one.
            # Without this a fired tranche resurrects the moment price dips
            # back below it, and the conditional book churns every wobble.
            hwm = self._round_hwm
            gauge = mark if hwm is None else (max(hwm, mark) if long
                                              else min(hwm, mark))
            self._round_hwm = gauge
            # B3's law, applied to the hosted TP: a target must CLEAR the
            # mark by the guard band, not merely exceed it. Between our read
            # and the venue's write the mark moves, and a target inside that
            # margin is refused ("should be higher than base_price") — the
            # same race the cross guard already solves for resting limits.
            priced = [(p, sh) for p, sh in priced
                      if (p > gauge + guard if long else p < gauge - guard)]
        if not priced:
            return []
        total = sum(sh for _, sh in priced)
        return [(p, adapter.round_qty(abs(held) * sh / total))
                for p, sh in priced]

    def _exits_cover(self, truth, held, idx, hosted):
        """M3: is the position already covered by exits resting on the
        venue? Hosted venues answer from the conditional book, others from
        our own rung-0 reduce-only orders."""
        want = abs(held)
        if want <= 0:
            return True
        if hosted:
            book = getattr(self.client, 'stop_orders', None)
            if book is None:
                return bool(truth['positions'].get(idx, {}).get('take_profit'))
            resting = sum(
                float(o.get('qty') or 0)
                for o in book(self.cfg['market_type'], self.cfg['symbol'])
                if 'TakeProfit' in (o.get('stopOrderType') or '')
                and int(o.get('positionIdx') or 0) == idx)
        else:
            resting = sum(o['qty'] for o in truth['orders']
                          if o['reduce_only'] and o['side'] == self._exit_side
                          and rung_of(o['link_id'], self.botid) == 0)
        # the venue rounds our shares, so a step of slack is expected
        return resting >= want - max(self.adapter.qty_step, want * 1e-6)

    def _close_remainder_at_best(self, held, basis):
        """M3 for a blown-through tranche round: every target already met —
        close what remains, marketable at the DEEPEST target (fills at
        target or better)."""
        cfg, adapter = self.cfg, self.adapter
        long = cfg['side'] == 'long'
        sign = 1.0 if long else -1.0
        prices = [adapter.round_price(basis * (1.0 + sign * t['at_avg_pct']))
                  for t in cfg['take_profit_tranches']]
        best = max(prices) if long else min(prices)
        self._gen += 1
        self.client.place_order(
            cfg['market_type'], cfg['symbol'], self._exit_side,
            adapter.fmt_qty(abs(held)), adapter.fmt_price(best),
            self._make_link(0),
            adapter.position_idx(self._exit_side, True) or 0,
            reduce_only=True, post_only=False, borrow=self._borrow)
        self.notify.event('tp', self.botid,
                          f'every tranche target met — closing the remainder '
                          f'at {best:.10g} or better')

    def _maintain_partial_tps(self, truth, targets, idx):
        """D23 hosted: tranche TPs live on the venue's conditional book —
        level-triggered, re-anchored whenever the average moves."""
        cfg, adapter = self.cfg, self.adapter
        want = {(adapter.fmt_price(p), adapter.fmt_qty(q))
                for p, q in targets if q > 0}
        have = {}
        for o in self.client.stop_orders(cfg['market_type'], cfg['symbol']):
            if int(o.get('positionIdx') or 0) != idx:
                continue                  # not ours to touch (I1's spirit, H3)
            if 'TakeProfit' in (o.get('stopOrderType') or ''):
                key = (adapter.fmt_price(float(o.get('triggerPrice') or 0)),
                       adapter.fmt_qty(float(o.get('qty') or 0)))
                have[key] = o
        for key, o in have.items():
            if key not in want:
                try:
                    self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                             o['orderId'])
                except VenueError as e:
                    if e.kind != 'gone':
                        raise
        placed = 0
        for p, q in targets:
            key = (adapter.fmt_price(p), adapter.fmt_qty(q))
            if q <= 0 or key in have:
                continue
            self.client.set_trading_stop(cfg['market_type'], cfg['symbol'],
                                         idx, take_profit=adapter.fmt_price(p),
                                         tp_size=adapter.fmt_qty(q))
            placed += 1
        if placed:
            self.notify.event('tp', self.botid,
                              f'{placed} tranche TP(s) resting venue-side')

    def _maintain_resting_exits(self, truth, targets):
        """D23 on the hostless venue: the tranche ladder IS several D21
        exits — rung 0, reduce-only, diff-shielded, adopted by identity."""
        cfg, adapter = self.cfg, self.adapter
        want = {(adapter.fmt_price(p), adapter.fmt_qty(q))
                for p, q in targets if q > 0}
        have = {}
        for o in truth['orders']:
            if (o['reduce_only'] and o['side'] == self._exit_side
                    and rung_of(o['link_id'], self.botid) == 0):
                have[(adapter.fmt_price(o['price']),
                      adapter.fmt_qty(o['qty']))] = o
        for key, o in have.items():
            if key not in want:
                try:
                    self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                             o['order_id'])
                except VenueError as e:
                    if e.kind != 'gone':
                        raise
        placed = 0
        for p, q in targets:
            key = (adapter.fmt_price(p), adapter.fmt_qty(q))
            if q <= 0 or key in have:
                continue
            self._gen += 1
            self.client.place_order(
                cfg['market_type'], cfg['symbol'], self._exit_side,
                adapter.fmt_qty(q), adapter.fmt_price(p), self._make_link(0),
                adapter.position_idx(self._exit_side, True) or 0,
                reduce_only=True, post_only=False, borrow=self._borrow)
            placed += 1
        if placed:
            self.notify.event('tp', self.botid,
                              f'{placed} tranche exit(s) resting')

    def _maintain_trailing(self, truth, basis, held, idx, armed=True):
        """D23: trailing rides the venue or does not exist. Set once per
        round; the venue moves it from there. M11: with tranches, it arms
        only AFTER the first target fills — a trail tighter than the first
        tranche closes the round before it can ever take profit (measured
        live 2026-08-06: 30 rounds averaging a small loss)."""
        pct = self.cfg.get('trailing_stop_pct')
        if not pct or not held or basis is None or not armed:
            return
        if truth['positions'].get(idx, {}).get('trailing_stop'):
            return
        dist = self.adapter.round_price(basis * pct)
        try:
            self.client.set_trading_stop(
                self.cfg['market_type'], self.cfg['symbol'], idx,
                trailing_stop=self.adapter.fmt_price(dist))
            self.notify.event('tp', self.botid,
                              f'trailing stop riding the venue, {dist:.10g} '
                              'behind')
        except VenueError as e:
            self.notify.event('warn', self.botid, f'trailing: {e}')

    def _martingale_round(self, truth, held, basis):
        """M3/M5/M6. Returns a dict to end the cycle early, None to continue
        to the ladder plan."""
        cfg, adapter = self.cfg, self.adapter
        idx = adapter.position_idx(self._entry_side, False) or 0
        if held == 0:
            completed = ((self._last_pos and abs(self._last_pos) > 0)
                         or (self._last_pos is None and truth['orders']
                             and any(rung_of(o['link_id'], self.botid)
                                     is not None for o in truth['orders'])))
            if completed and self._last_pos:
                # M14: a round that ended by LIQUIDATION or by the operator's
                # own hand is not a completed round — re-entering there walks
                # straight back into what just killed it. Ask the venue how
                # the position actually closed.
                how = self._how_round_ended()
                if how is not None and how != 'exit':
                    self._kill(truth, f'round ended by {how}, not by our exit '
                                      '— standing down (M14/D1)')
                    return {'round': how}
            if completed:
                if not cfg['repeat']:
                    self._kill(truth, 'round complete (TP hit), repeat off')
                    return {'round': 'complete'}
                self._round += 1
                self._anchor = None
                self._round_hwm = None          # M10: round-scoped
                self.notify.event('repeat', self.botid,
                                  f'round {self._round + 1} re-anchors at '
                                  'market (M5: from flat only)')
                # ONE venue read answers both cooldown and reinvest (H1),
                # then the completion latch clears so none of this re-runs
                # on the next flat cycle (H4a)
                if cfg.get('repeat_cooldown_seconds') or cfg.get('reinvest'):
                    fills = self._own_fills()
                    cd = cfg.get('repeat_cooldown_seconds') or 0.0
                    if cd and fills:
                        self._cool_until = (max(f['time_ms'] for f in fills)
                                            / 1000.0 + cd)
                        if self._now() < self._cool_until:
                            self.notify.event(
                                'repeat', self.botid,
                                f'cooling {cd:.0f}s from the TP fill '
                                '(M13, venue-anchored)')
                    if cfg.get('reinvest'):
                        scale = self._reinvest_scale(fills)
                        if self._scale != scale:
                            self._scale = scale
                            if abs(scale - 1.0) > 1e-9:
                                self.notify.event(
                                    'repeat', self.botid,
                                    f'reinvest: sizes x{scale:.4g} (M12, '
                                    f'last {HISTORY_WINDOW_DAYS}d of venue '
                                    'fills)')
                self._last_pos = 0.0             # the completion latch (H4a)
                # E2 across rounds (H4b): the closed round's safety ladder is
                # cancelled BEFORE any new base fires — this cycle cleans,
                # the next one opens
                stale = [o for o in truth['orders']
                         if rung_of(o['link_id'], self.botid) is not None]
                if stale:
                    for o in stale:
                        try:
                            self.client.cancel_order(cfg['market_type'],
                                                     cfg['symbol'],
                                                     o['order_id'])
                        except VenueError as e:
                            if e.kind != 'gone':
                                raise
                    return {'round': 'cleanup'}
            cd = cfg.get('repeat_cooldown_seconds') or 0.0
            if cd and self._cool_until is None and self._last_pos is None:
                # restart during a cooldown: re-derive the anchor from the
                # venue once — a first-ever start has no fills and skips this
                fills = self._own_fills()
                self._cool_until = ((max(f['time_ms'] for f in fills)
                                     / 1000.0 + cd) if fills else 0.0)
            if self._cool_until and self._now() < self._cool_until:
                return {'round': 'cooling'}
            if cfg.get('reinvest') and self._scale is None:
                self._scale = self._reinvest_scale(self._own_fills())
            # M12: 0.0 is a REAL factor (capital fully lost), not "unset" —
            # truthiness here re-entered at full size after a total loss.
            scale = (self._scale if (cfg.get('reinvest')
                                     and self._scale is not None) else 1.0)
            if cfg.get('reinvest') and scale <= 0.0:
                if not self._unplaceable_warned:
                    self._unplaceable_warned = True
                    self.notify.event(
                        'warn', self.botid,
                        'reinvest: realised losses have consumed the capital '
                        '— refusing to open another round (M12)')
                return {'round': 'capital_exhausted'}
            qty = adapter.round_qty(cfg['base_order_size'] * scale
                                    / truth['mark'])
            if qty <= 0 or not adapter.meets_minimum(qty, truth['mark']):
                if not self._unplaceable_warned:         # once, not once/sec
                    self._unplaceable_warned = True
                    self.notify.event('warn', self.botid,
                                      'base order below minimum')
                return {'round': 'unplaceable'}
            self._unplaceable_warned = False
            self._gen += 1
            try:
                self.client.place_market(cfg['market_type'], cfg['symbol'],
                                         self._entry_side,
                                         adapter.fmt_qty(qty), idx,
                                         link_id=self._make_link(0),
                                         borrow=self._borrow)
            except (VenueError, OSError) as e:      # E6: may have landed
                self._anchor = truth['mark']
                self._last_pos = 0.0
                self.notify.event('warn', self.botid,
                                  f'base order ambiguous ({e}) — assuming '
                                  'placed; the next read reconciles (E6)')
                return {'round': 'ambiguous'}
            self._anchor = truth['mark']
            self.notify.event('start', self.botid,
                              f'round {self._round + 1}: base '
                              f'{self._entry_side} {qty:.10g} at market')
            self._last_pos = 0.0
            return {'round_started': self._round + 1}

        # holding: the round is never without a venue-resting exit
        # (M3/D21/D23 — tranches are the same law, split into shares)
        hosted = getattr(self.client, 'hosts_position_tp', True)
        if self.cfg.get('take_profit_tranches'):
            targets = self._round_targets(
                basis, held, truth['mark'],
                guard=guard_band(truth['bid'], truth['ask']))
            # M11: a tranche has fired iff fewer targets remain than configured
            fired = len(targets) < len(self.cfg['take_profit_tranches'])
            self._maintain_trailing(truth, basis, held, idx, armed=fired)
            try:
                if not targets:
                    # M3 asks for a venue-resting exit, not for a NEW one.
                    # Once the high-water has passed every tranche, the
                    # exits placed earlier are still resting and will fill —
                    # adding another reduce-only order on top is refused for
                    # capacity (110017) and warns every cycle forever.
                    if not self._exits_cover(truth, held, idx, hosted):
                        self._close_remainder_at_best(held, basis)
                        return {'round': 'closing'}
                    return None
                if hosted:
                    self._maintain_partial_tps(truth, targets, idx)
                else:
                    self._maintain_resting_exits(truth, targets)
            except VenueError as e:
                if e.kind != 'ro_capacity':      # the ladder ignores these too
                    self.notify.event('warn', self.botid, f'tp: {e}')
            return None
        self._maintain_trailing(truth, basis, held, idx)
        targets = self._round_targets(basis, held)
        target = targets[0][0]
        tp_order = None
        if hosted:
            venue_tp = truth['positions'].get(idx, {}).get('take_profit')
        else:
            tp_order = next(
                (o for o in truth['orders']
                 if o['reduce_only'] and o['side'] == self._exit_side
                 and rung_of(o['link_id'], self.botid) == 0), None)
            venue_tp = tp_order['price'] if tp_order else None
        through = (truth['mark'] >= target if cfg['side'] == 'long'
                   else truth['mark'] <= target)
        if venue_tp is None and through:
            self._gen += 1
            link = self._make_link(0)
            self.client.place_order(
                cfg['market_type'], cfg['symbol'], self._exit_side,
                adapter.fmt_qty(abs(held)), adapter.fmt_price(target), link,
                adapter.position_idx(self._exit_side, True) or 0,
                reduce_only=True, post_only=False,     # marketable: target or better
                borrow=self._borrow)
            self.notify.event('tp', self.botid,
                              f'target {target:.10g} already met — closing the '
                              'round at target or better')
            return {'round': 'closing'}
        grew = self._last_pos is not None and abs(held) > abs(self._last_pos)
        if venue_tp is None or grew:
            try:
                if hosted:
                    self.client.set_trading_stop(
                        cfg['market_type'], cfg['symbol'], idx,
                        take_profit=adapter.fmt_price(target))
                else:                        # D21: the venue-resting exit
                    if tp_order is not None:
                        try:
                            self.client.cancel_order(cfg['market_type'],
                                                     cfg['symbol'],
                                                     tp_order['order_id'])
                        except VenueError as e:
                            if e.kind != 'gone':
                                raise
                    self._gen += 1
                    self.client.place_order(
                        cfg['market_type'], cfg['symbol'], self._exit_side,
                        adapter.fmt_qty(abs(held)), adapter.fmt_price(target),
                        self._make_link(0),
                        adapter.position_idx(self._exit_side, True) or 0,
                        reduce_only=True, post_only=False, borrow=self._borrow)
                if venue_tp is None:
                    self.notify.event('tp', self.botid,
                                      f'round TP resting: {target:.10g}')
            except VenueError as e:
                self.notify.event('warn', self.botid, f'tp: {e}')
        return None

    def _maybe_seed(self, truth, held, ref):
        """D9/S2/S3: first cycle, flat, no owned orders resting — market-buy
        one lot per exit-side rung. Observable as done from the venue alone."""
        if not self.cfg.get('seed') or held != 0 or self._last_pos is not None:
            return False
        if any(rung_of(o['link_id'], self.botid) is not None
               for o in truth['orders']):
            return False
        rungs = grid_rungs(self.cfg, self.adapter)
        exit_rungs = split(self.cfg['side'], rungs, ref)['exits']
        qty = self.adapter.round_qty(
            lot(self.cfg, self.adapter, ref) * len(exit_rungs))
        if qty <= 0 or not self.adapter.meets_minimum(qty, ref):
            return False
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        self._gen += 1
        try:
            self.client.place_market(self.cfg['market_type'],
                                     self.cfg['symbol'], self._entry_side,
                                     self.adapter.fmt_qty(qty), idx,
                                     link_id=self._make_link(0),
                                     borrow=self._borrow)
        except (VenueError, OSError) as e:
            # E6: the write may have landed. Treating it as done is the SAFE
            # direction here — a re-fired seed doubles the ladder, while a
            # lost seed is visible as an uncovered position next cycle.
            self.notify.event('warn', self.botid,
                              f'seed ambiguous ({e}) — assuming placed; the '
                              'next truth read reconciles (E6)')
            return True
        self.notify.event('seed', self.botid,
                          f'{self._entry_side} {qty:.10g} at market for '
                          f'{len(exit_rungs)} exit rungs')
        return True

    def _make_link(self, rung):
        mk = getattr(self.client, 'make_link', None)
        return mk(self.botid, rung, self._gen) if mk \
            else make_link(self.botid, rung, self._gen)

    def _sticky(self, ref):
        """B2: the split ref moves only past the band, then snaps to current.
        Zero band is identical to unset."""
        frac = self.cfg.get('split_hysteresis_rungs') or 0.0
        if frac <= 0:
            return ref
        if (self._held_ref is None
                or abs(ref - self._held_ref) > self._min_gap * frac):
            self._held_ref = ref
        return self._held_ref

    def _held(self, truth):
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        pos = truth['positions'].get(idx)
        if pos and pos['side'] and pos['side'] != self._entry_side:
            return None, None              # S4: a position we cannot explain
        return (pos['size'] if pos else 0.0), (pos['avg_entry'] if pos else None)

    def _would_cross(self, order, bid, ask):
        """B3/G13: one band, imported — nothing rests near the opposite quote."""
        if bid is None or ask is None:
            return False
        guard = guard_band(bid, ask)
        if order['side'] == 'Buy':
            return order['price'] >= ask - guard
        return order['price'] <= bid + guard

    def _cooling(self, key, now):
        entry = self._cooldown.get(key)
        if not entry:
            return False
        if now >= entry[0]:
            del self._cooldown[key]
            return False
        return True

    def _do_backoff(self, now):
        if now > self._backoff_until + BACKOFF_CEILING:
            self._backoff = 0.0            # quiet spell: the schedule restarts
        self._backoff = min(max(BACKOFF_BASE, self._backoff * 2.0),
                            BACKOFF_CEILING)
        self._backoff_until = now + self._backoff
        if self._backoff > self._backoff_emitted:
            self._backoff_emitted = self._backoff
            self.notify.event('backoff', self.botid,
                              f'margin: growth halted {self._backoff:.0f}s')

    def _account_flaps(self, resting_keys, pos_stable, now):
        """B5: placed-but-not-resting while the position held still is a book
        race; a rung whose position moved is trading and is never cooled."""
        for key in self._placed_last:
            if key in resting_keys or not pos_stable:
                self._flap.pop(key, None)
                continue
            strikes = self._flap.get(key, 0) + 1
            self._flap[key] = strikes
            if strikes >= FLAP_LIMIT:
                self._cooldown[key] = (now + FLAP_COOLDOWN, 'flap')   # B6
                self._flap.pop(key)
                self.notify.event('backoff', self.botid,
                                  f'rung {key[0]} {key[1]} flapping: '
                                  f'cooling {FLAP_COOLDOWN:.0f}s')

    def cycle(self, equity=None):
        if not self.alive:
            return None
        cfg, adapter, now = self.cfg, self.adapter, self._now()
        truth = self.client.read_symbol_truth(
            cfg['market_type'], cfg['symbol'],
            cfg.get('funding_interval_minutes', 480.0))
        held, basis = self._held(truth)
        if held is None:                           # S4: halt and alert
            if not self._anomaly_warned:
                self._anomaly_warned = True
                self.notify.event('warn', self.botid,
                                  'position on our index has the WRONG side — '
                                  'halting this bot until an operator looks')
            return {'anomaly': True}
        if basis is None:              # a venue-reported basis overrules the
            basis = cfg.get('assumed_avg_entry')   # config field (V6, from v2)

        reason = self._stop_hit(truth, equity)          # X1: before everything
        if reason:
            self._execute_stop(truth, held, reason)
            return None
        self._maintain_server_stop(truth, held)

        pos_stable = self._last_pos is not None and held == self._last_pos

        if self._maybe_seed(truth, held, truth['split_ref']):
            self._last_pos = 0.0                   # the fill lands next cycle
            return {'seeded': True}

        if self._last_pos is not None and held != self._last_pos:
            grew = abs(held) > abs(self._last_pos)
            self.notify.event('fill' if grew else 'exit', self.botid,
                              f'position {self._last_pos:.10g} -> {held:.10g}')

        if cfg['strategy'] == 'martingale':
            early = self._martingale_round(truth, held, basis)
            if early is not None:
                return early
        elif (self._last_pos and abs(self._last_pos) > 0 and held == 0):
            links_now = {o['link_id'] for o in truth['orders']}
            if not (self._exit_links_last - links_now):      # no exit of ours
                # E9: a venue that answers an EMPTY position list (under load,
                # or on an account-type mismatch) is indistinguishable from
                # flat — and this path is irreversible. Confirm across
                # consecutive reads before killing.
                self._flat_streak += 1
                if self._flat_streak < FLAT_CONFIRMATIONS:
                    self.notify.event(
                        'warn', self.botid,
                        f'position reads flat but our exits still rest — '
                        f'confirming ({self._flat_streak}/'
                        f'{FLAT_CONFIRMATIONS}) before standing down (E9)')
                    return {'confirming_flat': self._flat_streak}
                self._kill(truth, 'position closed externally (D1)')
                return None
        if held:
            self._flat_streak = 0

        ref = self._sticky(truth['split_ref'])     # W2: the one anchor
        bid, ask = truth['bid'], truth['ask']
        resting_exits = {rung_of(o['link_id'], self.botid)
                         for o in truth['orders']
                         if o['side'] == self._exit_side
                         and rung_of(o['link_id'], self.botid) is not None}
        orders_view = truth['orders']
        if (cfg['strategy'] == 'martingale'
                and not getattr(self.client, 'hosts_position_tp', True)):
            orders_view = [o for o in orders_view       # D21: rung 0 is the
                           if not (o['reduce_only']      # round exit — shielded
                                   and o['side'] == self._exit_side
                                   and rung_of(o['link_id'], self.botid) == 0)]
        if cfg['strategy'] == 'martingale':
            if cfg.get('reinvest') and self._scale is None:
                self._scale = self._reinvest_scale(self._own_fills())
            if self._anchor is None:
                # M15: a restart mid-round must NOT re-anchor on the average
                # entry — that deepens every remaining rung and un-suppresses
                # rungs that already filled, pushing the position past the
                # capital the validator approved. The venue still holds the
                # answer: any resting safety order inverts to the anchor.
                for o in truth['orders']:
                    r = rung_of(o['link_id'], self.botid)
                    if r and not o['reduce_only']:
                        found = anchor_from_rung(cfg, o['price'], r)
                        if found:
                            self._anchor = adapter.round_price(found)
                            self.notify.event(
                                'repeat', self.botid,
                                f'round anchor recovered from the venue: '
                                f'{self._anchor:.10g} (M15)')
                            break
            desired = plan_martingale(cfg, adapter, self._anchor or basis or ref,
                                      ref, held,
                                      scale=(self._scale
                                             if cfg.get('reinvest')
                                             and self._scale is not None
                                             else 1.0))
        else:
            desired = plan_grid(cfg, adapter, ref, held, basis, bid, ask,
                                resting_exits)
        live = window(desired, ref, cfg['place_within_pct'])          # W1
        to_cancel, _ = diff(desired, orders_view, self.botid)         # full
        _, to_create = diff(live, orders_view, self.botid)            # windowed
        amends, cancels, creates = pair_amends(to_cancel, to_create, self.botid)

        for order, want in amends:
            try:
                self.client.amend_order(cfg['market_type'], cfg['symbol'],
                                        order['order_id'],
                                        adapter.fmt_qty(want['qty']))
                self.notify.event('amend', self.botid,
                                  f"{want['side']}@{want['price']:.10g} "
                                  f"qty -> {want['qty']:.10g}")
            except VenueError as e:
                if e.kind not in ('gone', 'not_modified'):
                    self.notify.event('warn', self.botid, f'amend: {e}')

        for order in cancels:                       # E2: cancels before creates
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         order['order_id'])
                self.notify.event('cancel', self.botid,
                                  f"{order['side']}@{order['price']:.10g}")
            except VenueError as e:
                if e.kind != 'gone':
                    self.notify.event('warn', self.botid, f'cancel: {e}')

        placed_now, placed_exit_links, skipped = set(), set(), 0
        if now < self._backoff_until:               # B7: growth only is halted
            creates, skipped = [], len(creates)
        for want in creates:
            key = (want['rung'], want['side'])
            if self._cooling(key, now) or self._would_cross(want, bid, ask):
                self.notify.event('skip', self.botid,
                                  f"{want['side']}@{want['price']:.10g}")
                skipped += 1
                continue
            self._gen += 1
            link = self._make_link(want['rung'])
            idx = adapter.position_idx(want['side'], want['reduce_only']) or 0
            try:
                self.client.place_order(
                    cfg['market_type'], cfg['symbol'], want['side'],
                    adapter.fmt_qty(want['qty']), adapter.fmt_price(want['price']),
                    link, idx, want['reduce_only'], borrow=self._borrow)
                placed_now.add(key)
                if want['side'] == self._exit_side:
                    placed_exit_links.add(link)
                self.notify.event('placed', self.botid,
                                  f"{want['side']}@{want['price']:.10g} "
                                  f"x {want['qty']:.10g}")
            except VenueError as e:
                if e.kind == 'margin':   # account-level: B7's backoff, never
                    self.notify.event('margin', self.botid, str(e))
                    self._do_backoff(now)              # a rung-flap matter
                    break
                # rung-level failure: an ATTEMPT — placed-but-not-resting
                # strikes the flap next cycle (B5), so a rung that fails
                # repeatedly COOLS instead of warning once per cycle (the
                # 170037 incident: ~1500 warns before the switch was found)
                placed_now.add(key)
                if e.kind not in ('ro_capacity', 'post_only_reject'):
                    self.notify.event('warn', self.botid, f'place: {e}')

        sellable = held and abs(held) > 0 and cfg['strategy'] == 'grid'
        has_exits = any(o['side'] == self._exit_side for o in desired)
        if sellable and not has_exits:             # S5: state, warned once
            if not self._uncovered_warned:
                self._uncovered_warned = True
                self.notify.event('warn', self.botid,
                                  'holding, but nothing harvestable — basis '
                                  'beyond the range; position left to you')
        else:
            self._uncovered_warned = False

        resting_keys = {(rung_of(o['link_id'], self.botid), o['side'])
                        for o in truth['orders']}
        self._account_flaps(resting_keys, pos_stable, now)
        self._placed_last = placed_now
        self._exit_links_last = placed_exit_links | {
            o['link_id'] for o in truth['orders']
            if o['side'] == self._exit_side
            and rung_of(o['link_id'], self.botid) is not None}
        self._last_pos = held
        return {'desired': len(desired), 'live': len(live),
                'amends': len(amends), 'cancels': len(cancels),
                'creates': len(placed_now), 'skips': skipped}
