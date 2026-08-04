# The loop with its guards (SPEC E2, E3, W1, B3-B7, T2).
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .exchange.errors import VenueError
from .ladder import (grid_rungs, guard_band, lot, min_gap, plan_grid,
                     plan_martingale, sellable_base, split)
from .window import window

FLAP_LIMIT = 3          # B5: strikes before a (rung, side) cools
FLAP_COOLDOWN = 60.0
BACKOFF_BASE = 30.0     # B7: margin backoff, doubling to the ceiling
BACKOFF_CEILING = 300.0


class Bot:
    # E3/S6: the reset-on-restart list, complete and asserted by spec —
    # _last_pos (fill baseline, re-seeded first cycle), _gen (restart-unique),
    # _held_ref (re-anchors), _placed_last/_flap/_cooldown (churn guards),
    # _backoff*/_exit_links_last/_uncovered_warned/_anomaly_warned (latches).
    # Everything else the bot knows comes from the venue each cycle.

    def __init__(self, cfg, adapter, client, notifier, gen_seed, clock=None):
        self.cfg = cfg
        self.adapter = adapter
        self.client = client
        self.notify = notifier
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
        self._round = 0

    def _kill(self, truth, reason):
        """D1/S7: cancel every owned order, stand down, never restart. X4:
        the event states what still rests."""
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
        qty = self._flatten_scope(held)
        if qty > 0:
            self._gen += 1
            try:
                self.client.place_market(
                    cfg['market_type'], cfg['symbol'], self._exit_side,
                    adapter.fmt_qty(qty),
                    adapter.position_idx(self._exit_side, True) or 0,
                    reduce_only=True, link_id=self._make_link(0))
            except VenueError as e:
                self.notify.event('warn', self.botid, f'flatten: {e}')
        floor = abs(held) - qty
        residue = (f'floor core {floor:.10g} REMAINS, unprotected'
                   if floor > 1e-12 else 'position flat')
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
        if venue_sl is not None and abs(venue_sl - want) < 1e-9:
            return                                    # the venue already agrees
        try:
            partial = self._flatten_scope(held) < abs(held)
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
            if completed:
                if not cfg['repeat']:
                    self._kill(truth, 'round complete (TP hit), repeat off')
                    return {'round': 'complete'}
                self._round += 1
                self._anchor = None
                self.notify.event('repeat', self.botid,
                                  f'round {self._round + 1} re-anchors at '
                                  'market (M5: from flat only)')
            qty = adapter.round_qty(cfg['base_order_size'] / truth['mark'])
            if qty <= 0 or not adapter.meets_minimum(qty, truth['mark']):
                self.notify.event('warn', self.botid, 'base order below minimum')
                return {'round': 'unplaceable'}
            self._gen += 1
            self.client.place_market(cfg['market_type'], cfg['symbol'],
                                     self._entry_side, adapter.fmt_qty(qty),
                                     idx, link_id=self._make_link(0))
            self._anchor = truth['mark']
            self.notify.event('start', self.botid,
                              f'round {self._round + 1}: base '
                              f'{self._entry_side} {qty:.10g} at market')
            self._last_pos = 0.0
            return {'round_started': self._round + 1}

        # holding: the round is never without a venue-resting exit (M3/D21)
        target = self._round_target(basis)
        hosted = getattr(self.client, 'hosts_position_tp', True)
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
                reduce_only=True, post_only=False)     # marketable: target or better
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
                        reduce_only=True, post_only=False)
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
        self.client.place_market(self.cfg['market_type'], self.cfg['symbol'],
                                 self._entry_side, self.adapter.fmt_qty(qty),
                                 idx, link_id=self._make_link(0))
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
        if basis is None:
            basis = cfg.get('assumed_avg_entry')

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
                self._kill(truth, 'position closed externally (D1)')
                return None

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
            desired = plan_martingale(cfg, adapter, self._anchor or basis or ref,
                                      ref, held)
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
                    link, idx, want['reduce_only'])
                placed_now.add(key)
                if want['side'] == self._exit_side:
                    placed_exit_links.add(link)
                self.notify.event('placed', self.botid,
                                  f"{want['side']}@{want['price']:.10g} "
                                  f"x {want['qty']:.10g}")
            except VenueError as e:
                if e.kind == 'margin':
                    self.notify.event('margin', self.botid, str(e))
                    self._do_backoff(now)
                    break
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
