# The loop with its guards (SPEC E2, E3, W1, B3-B7, T2).
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .exchange.bybit.truth import read_symbol_truth
from .exchange.errors import VenueError
from .ladder import grid_rungs, guard_band, lot, min_gap, plan_grid, split
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
        self._min_gap = min_gap(grid_rungs(cfg, adapter))
        self.alive = True
        self._exit_links_last = set()  # S7: the ownership discriminator
        self._uncovered_warned = False
        self._anomaly_warned = False

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
        self.client.place_market(self.cfg['market_type'], self.cfg['symbol'],
                                 self._entry_side, self.adapter.fmt_qty(qty),
                                 idx)
        self.notify.event('seed', self.botid,
                          f'{self._entry_side} {qty:.10g} at market for '
                          f'{len(exit_rungs)} exit rungs')
        return True

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

    def cycle(self):
        if not self.alive:
            return None
        cfg, adapter, now = self.cfg, self.adapter, self._now()
        truth = read_symbol_truth(self.client, cfg['market_type'], cfg['symbol'],
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
        pos_stable = self._last_pos is not None and held == self._last_pos

        if self._maybe_seed(truth, held, truth['split_ref']):
            self._last_pos = 0.0                   # the fill lands next cycle
            return {'seeded': True}

        if self._last_pos is not None and held != self._last_pos:
            grew = abs(held) > abs(self._last_pos)
            self.notify.event('fill' if grew else 'exit', self.botid,
                              f'position {self._last_pos:.10g} -> {held:.10g}')

        if (self._last_pos and abs(self._last_pos) > 0 and held == 0):
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
        desired = plan_grid(cfg, adapter, ref, held, basis, bid, ask,
                            resting_exits)
        live = window(desired, ref, cfg['place_within_pct'])          # W1
        to_cancel, _ = diff(desired, truth['orders'], self.botid)     # full
        _, to_create = diff(live, truth['orders'], self.botid)        # windowed
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
            link = make_link(self.botid, want['rung'], self._gen)
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

        sellable = held and abs(held) > 0
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
