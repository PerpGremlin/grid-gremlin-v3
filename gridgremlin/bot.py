# The loop (SPEC E2, E3, W1, T2). One bot, one cycle.
from .apply import diff, make_botid, make_link, pair_amends
from .exchange.bybit.truth import read_symbol_truth
from .exchange.errors import VenueError
from .ladder import plan_grid
from .window import window


class Bot:
    # E3: in-memory state, all reset on restart by design — _last_pos (fill
    # detector baseline, re-seeded first cycle so no phantom fill) and _gen
    # (restart-unique link suffix). The exchange is the durable state.

    def __init__(self, cfg, adapter, client, notifier, gen_seed):
        self.cfg = cfg
        self.adapter = adapter
        self.client = client
        self.notify = notifier
        self.botid = make_botid(cfg['market_type'], cfg['symbol'], cfg['side'])
        self._gen = gen_seed
        self._last_pos = None
        self._entry_side = 'Buy' if cfg['side'] == 'long' else 'Sell'

    def _held(self, truth):
        idx = self.adapter.position_idx(self._entry_side, False) or 0
        pos = truth['positions'].get(idx)
        return (pos['size'] if pos else 0.0), (pos['avg_entry'] if pos else None)

    def cycle(self):
        cfg, adapter = self.cfg, self.adapter
        truth = read_symbol_truth(self.client, cfg['market_type'], cfg['symbol'],
                                  cfg.get('funding_interval_minutes', 480.0))
        held, basis = self._held(truth)
        if basis is None:
            basis = cfg.get('assumed_avg_entry')

        if self._last_pos is not None and held != self._last_pos:
            grew = abs(held) > abs(self._last_pos)
            self.notify.event('fill' if grew else 'exit', self.botid,
                              f'position {self._last_pos:.10g} -> {held:.10g}')

        ref = truth['split_ref']
        desired = plan_grid(cfg, adapter, ref, held, basis)
        live = window(desired, ref, cfg['place_within_pct'])          # W1
        to_cancel, _ = diff(desired, truth['orders'], self.botid)     # full
        _, to_create = diff(live, truth['orders'], self.botid)        # windowed
        amends, cancels, creates = pair_amends(to_cancel, to_create, self.botid)

        for order, want in amends:                                    # qty only
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

        for order in cancels:                                         # E2 order
            try:
                self.client.cancel_order(cfg['market_type'], cfg['symbol'],
                                         order['order_id'])
                self.notify.event('cancel', self.botid,
                                  f"{order['side']}@{order['price']:.10g}")
            except VenueError as e:
                if e.kind != 'gone':
                    self.notify.event('warn', self.botid, f'cancel: {e}')

        for want in creates:
            self._gen += 1
            link = make_link(self.botid, want['rung'], self._gen)
            idx = adapter.position_idx(want['side'], want['reduce_only']) or 0
            try:
                self.client.place_order(
                    cfg['market_type'], cfg['symbol'], want['side'],
                    adapter.fmt_qty(want['qty']), adapter.fmt_price(want['price']),
                    link, idx, want['reduce_only'])
                self.notify.event('placed', self.botid,
                                  f"{want['side']}@{want['price']:.10g} "
                                  f"x {want['qty']:.10g}")
            except VenueError as e:
                if e.kind == 'margin':
                    self.notify.event('margin', self.botid, str(e))
                    break                                # halt growth only (E7)
                if e.kind not in ('ro_capacity', 'post_only_reject'):
                    self.notify.event('warn', self.botid, f'place: {e}')

        self._last_pos = held
        return {'desired': len(desired), 'live': len(live),
                'amends': len(amends), 'cancels': len(cancels),
                'creates': len(creates)}
