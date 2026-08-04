# The loop with its guards (SPEC E2, E3, W1, B3-B7, T2).
import time

from .apply import diff, make_botid, make_link, pair_amends, rung_of
from .exchange.bybit.truth import read_symbol_truth
from .exchange.errors import VenueError
from .ladder import guard_band, plan_grid
from .window import window

FLAP_LIMIT = 3          # B5: strikes before a (rung, side) cools
FLAP_COOLDOWN = 60.0
BACKOFF_BASE = 30.0     # B7: margin backoff, doubling to the ceiling
BACKOFF_CEILING = 300.0


class Bot:
    # E3: in-memory state, reset on restart by design — the fill baseline
    # (_last_pos, re-seeded first cycle), the link counter (_gen,
    # restart-unique), and the guards' counters/clocks below.

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

    def _held(self, truth):
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        pos = truth['positions'].get(idx)
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
        cfg, adapter, now = self.cfg, self.adapter, self._now()
        truth = read_symbol_truth(self.client, cfg['market_type'], cfg['symbol'],
                                  cfg.get('funding_interval_minutes', 480.0))
        held, basis = self._held(truth)
        if basis is None:
            basis = cfg.get('assumed_avg_entry')
        pos_stable = self._last_pos is not None and held == self._last_pos

        if self._last_pos is not None and held != self._last_pos:
            grew = abs(held) > abs(self._last_pos)
            self.notify.event('fill' if grew else 'exit', self.botid,
                              f'position {self._last_pos:.10g} -> {held:.10g}')

        ref, bid, ask = truth['split_ref'], truth['bid'], truth['ask']
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

        placed_now, skipped = set(), 0
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

        resting_keys = {(rung_of(o['link_id'], self.botid), o['side'])
                        for o in truth['orders']}
        self._account_flaps(resting_keys, pos_stable, now)
        self._placed_last = placed_now
        self._last_pos = held
        return {'desired': len(desired), 'live': len(live),
                'amends': len(amends), 'cancels': len(cancels),
                'creates': len(placed_now), 'skips': skipped}
