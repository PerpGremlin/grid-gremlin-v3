# The HL venue facade: the same client surface the Bot drives on Bybit
# (read_symbol_truth, read_wallet, place/cancel/amend, make_link). Writes sign
# with the TESTNET agent key; mainnet is unconstructible (F5).
from ...adapters import _d
from ..errors import VenueError
from .adapters import HLPerpAdapter
from .exchange import ExchangeClient
from .signing import link_to_cloid
from . import truth as hl_truth

MAX_LINK_LEN = 16
GEN_CHARS = 4
_B36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def _b36(n):
    n %= 36 ** GEN_CHARS
    out = ''
    for _ in range(GEN_CHARS):
        out = _B36[n % 36] + out
        n //= 36
    return out


class HLVenueClient(ExchangeClient):
    env_label = 'hyperliquid'
    hosts_position_tp = False    # D21: the round exit is a resting order here

    def __init__(self, **kw):
        super().__init__(**kw)
        self._universe = None          # instrument metadata (A1), fetched once

    def _entry(self, coin):
        if self._universe is None:
            self._universe = {e['name']: (i, e) for i, e in
                              enumerate(self.meta()['universe'])}
        if coin not in self._universe:
            raise VenueError(f'{coin}: not in the HL universe')
        return self._universe[coin]

    def _adapter(self, coin):
        _, entry = self._entry(coin)
        return HLPerpAdapter(hl_truth.parse_instrument(entry))

    # --- the Bot's surface ---------------------------------------------------

    def make_link(self, botid, rung, gen):
        link = f'{botid}-{rung}-{_b36(gen)}'
        link_to_cloid(link)                      # refuses > 16 bytes
        return link

    def read_wallet(self):
        return hl_truth.read_wallet(self)

    def read_symbol_truth(self, market_type, symbol, funding_interval=60.0):
        return hl_truth.read_symbol_truth(self, symbol)

    def place_order(self, market_type, symbol, side, qty, price, link_id,
                    position_idx=0, reduce_only=False, post_only=True):
        asset, _ = self._entry(symbol)
        return super().place_order(asset, side, qty, price,
                                   order_link_id=link_id,
                                   reduce_only=reduce_only,
                                   post_only=post_only)

    def cancel_order(self, market_type, symbol, order_id):
        asset, _ = self._entry(symbol)
        r = super().cancel_order(asset, order_id=int(order_id))
        if r['status'] == 'gone':
            raise VenueError(f'{order_id}: already gone', kind='gone')
        return r

    def amend_order(self, market_type, symbol, order_id, qty):
        """HL's modify needs the FULL body — recover it from a fresh read;
        a miss is 'gone' and the caller's fallback recreates (E6)."""
        asset, _ = self._entry(symbol)
        resting = hl_truth.read_orders(self.open_orders(symbol), symbol)
        match = next((o for o in resting if o['order_id'] == str(order_id)),
                     None)
        if match is None:
            raise VenueError(f'{order_id}: not resting', kind='gone')
        return super().amend_order(
            asset, match['side'], qty, self._adapter(symbol).fmt_price(
                match['price']),
            order_id=int(order_id), reduce_only=match['reduce_only'])

    def place_market(self, market_type, symbol, side, qty, position_idx=0,
                     reduce_only=False, link_id=None):
        """HL has no market type: an aggressive IOC limit is the idiom."""
        asset, entry = self._entry(symbol)
        adapter = self._adapter(symbol)
        names = [e['name'] for e in self.meta()['universe']]
        _, ctxs = self.meta_and_ctxs()
        mark = float(ctxs[names.index(symbol)]['markPx'])
        px = mark * (1.05 if side == 'Buy' else 0.95)
        order = {'a': asset, 'b': side == 'Buy', 'p': adapter.fmt_price(px),
                 's': qty, 'r': bool(reduce_only),
                 't': {'limit': {'tif': 'Ioc'}}}
        if link_id:
            order['c'] = link_to_cloid(link_id)
        action = {'type': 'order', 'orders': [order], 'grouping': 'na'}
        status, oid = self._statuses(self._post_action(action), 1)[0]
        if status == 'error':
            raise VenueError(f'market: {oid}', kind='other')
        return {'status': status, 'oid': oid}

    def set_trading_stop(self, *a, **kw):
        raise VenueError('HL cannot host a position-level TP/SL — trigger '
                         'orders are a later phase', kind='other')
