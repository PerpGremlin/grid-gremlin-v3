"""HL /exchange writes — place / cancel / amend / leverage. Phase 2 of the port.

Each write is an EIP-712-signed action (signing.py) POSTed to /exchange with a
nonce. The discipline mirrors the Bybit client's hard-won stances:

- **Nonce = strictly-increasing ms timestamp per account.** HL rejects reused or
  stale nonces; two processes signing for one account WILL collide — the
  single-fleet-process rule (docs/HYPERLIQUID.md §6.4) is load-bearing here.
- **Prices and sizes are STRINGS**, produced by the adapter's fmt_price/fmt_qty.
  A float sneaking in would hash differently than it serialises — so floats are
  refused at the msgpack layer and here by type check, never coerced.
- **Ambiguity is honoured.** A timeout/5xx after the request was sent means the
  order MAY exist: HLError(ambiguous=True), defer to reconcile — never
  synthesize a rejection. A clean {'status':'err'} or per-order error is a real
  rejection and raises plainly.
- The wallet may be an **agent/API wallet** signing for a master account: the
  signer (HL_PRIVATE_KEY) and the account read for truth (HL_ACCOUNT_ADDRESS)
  are allowed to differ. With no explicit address, the wallet's own address is
  the account.

Key + address come from `.env` (HL_PRIVATE_KEY / HL_ACCOUNT_ADDRESS).
"""
import os
import time
import urllib.error

from .client import HLError, InfoClient
from .signing import link_to_cloid, priv_to_address, sign_l1_action


def _kind_from_text(text):
    t = str(text).lower()
    if 'immediately match' in t:
        return 'post_only_reject'
    if 'margin' in t:
        return 'margin'
    return 'other'


class ExchangeClient(InfoClient):
    def __init__(self, env=None, address=None, private_key=None):
        super().__init__(env=env, address=address)
        self.private_key = private_key or os.environ.get('HL_PRIVATE_KEY')
        if not self.private_key:
            raise HLError(0, 'no signing key — set HL_PRIVATE_KEY in .env (an agent/API '
                             'wallet key, not the main account key, is the safe choice)')
        self.wallet = priv_to_address(self.private_key)
        if not self.address:
            self.address = self.wallet       # no agent split: wallet IS the account
        self._last_nonce = 0

    def _nonce(self):
        """Strictly increasing even when two writes land in the same millisecond."""
        n = max(int(time.time() * 1000), self._last_nonce + 1)
        self._last_nonce = n
        return n

    def _post_action(self, action):
        nonce = self._nonce()
        sig = sign_l1_action(self.private_key, action, None, nonce,
                             is_mainnet=(self.env == 'mainnet'))
        payload = {'action': action, 'nonce': nonce, 'signature': sig,
                   'vaultAddress': None, 'expiresAfter': None}
        try:
            resp = self._post('/exchange', payload, retry_429=False)
        except HLError as e:
            # 429 pre-rejects (not executed) — plain. 5xx: fate unknown — ambiguous.
            if e.status >= 500:
                raise HLError(e.status, f'{action["type"]}: {e.body[:200]}',
                              e.body, ambiguous=True) from e
            raise
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            raise HLError(0, f'{action["type"]}: network failure after send — the write '
                             f'may have landed; reconcile decides ({e})',
                          ambiguous=True) from e
        if resp.get('status') != 'ok':
            raise HLError(200, f'{action["type"]}: {resp.get("response")}', str(resp))
        return (resp.get('response') or {}).get('data') or {}

    @staticmethod
    def _statuses(data, n):
        """Per-order outcomes: ['resting'|'filled'|error-string, ...]. HL reports each
        order in a batch separately — a partial failure must not read as success."""
        sts = data.get('statuses') or [{}] * n
        out = []
        for st in sts:
            if 'resting' in st:
                out.append(('resting', st['resting'].get('oid')))
            elif 'filled' in st:
                out.append(('filled', st['filled'].get('oid')))
            elif 'success' in st or st == 'success':
                out.append(('ok', None))
            else:
                out.append(('error', st.get('error') if isinstance(st, dict) else str(st)))
        return out

    @staticmethod
    def _order_wire(asset, side, qty, price, link_id, reduce_only, post_only):
        if not (isinstance(qty, str) and isinstance(price, str)):
            raise TypeError('qty/price must be adapter-formatted STRINGS '
                            '(a float would hash differently than it serialises)')
        wire = {'a': int(asset), 'b': side == 'Buy', 'p': price, 's': qty,
                'r': bool(reduce_only), 't': {'limit': {'tif': 'Alo' if post_only else 'Gtc'}}}
        if link_id:
            wire['c'] = link_to_cloid(link_id)
        return wire

    # --- writes ---
    def place_order(self, asset, side, qty, price, order_link_id=None,
                    reduce_only=False, post_only=True):
        """One post-only (Alo) limit order. Returns ('resting'|'filled', oid) or
        raises with HL's per-order error text (e.g. the post-only-would-cross
        reject — the bot's book-guard makes that rare, same as Bybit)."""
        action = {'type': 'order',
                  'orders': [self._order_wire(asset, side, qty, price,
                                              order_link_id, reduce_only, post_only)],
                  'grouping': 'na'}
        status, oid = self._statuses(self._post_action(action), 1)[0]
        if status == 'error':
            raise HLError(200, f'order rejected: {oid}',
                          kind=_kind_from_text(oid))
        return {'status': status, 'oid': oid}

    def cancel_order(self, asset, order_id=None, order_link_id=None):
        """Cancel by oid, or by our cloid (the link_id) — link takes priority to
        mirror the Bybit client's identity-first cancels."""
        if order_link_id:
            action = {'type': 'cancelByCloid',
                      'cancels': [{'asset': int(asset), 'cloid': link_to_cloid(order_link_id)}]}
        elif order_id is not None:
            action = {'type': 'cancel',
                      'cancels': [{'a': int(asset), 'o': int(order_id)}]}
        else:
            raise ValueError('cancel needs order_id or order_link_id')
        status, detail = self._statuses(self._post_action(action), 1)[0]
        if status == 'error':
            # "order was never placed / already canceled / filled" = the Bybit
            # ORDER_GONE class: the cancel's goal (no resting order) is already
            # met — idempotent success, not a failure.
            if 'never placed' in str(detail) or 'already' in str(detail) or 'filled' in str(detail):
                return {'status': 'gone', 'detail': detail}
            raise HLError(200, f'cancel rejected: {detail}')
        return {'status': 'ok', 'detail': detail}

    def amend_order(self, asset, side, qty, price, order_id=None, order_link_id=None,
                    reduce_only=False, post_only=True):
        """Modify a resting order IN PLACE (HL batchModify). Same-price qty
        decrease keeps queue priority — the reason amend exists (CHANGELOG
        2026-07-26). The modify names the order by oid or by our cloid and must
        carry the FULL new order body. The bot keeps its fallback-to-recreate."""
        oid = int(order_id) if order_id is not None else link_to_cloid(order_link_id)
        action = {'type': 'batchModify', 'modifies': [{
            'oid': oid,
            'order': self._order_wire(asset, side, qty, price, order_link_id,
                                      reduce_only, post_only)}]}
        status, detail = self._statuses(self._post_action(action), 1)[0]
        if status == 'error':
            raise HLError(200, f'amend rejected: {detail}')
        return {'status': status, 'oid': detail}

    def update_leverage(self, asset, leverage, is_cross=True):
        """The set-leverage assertion (settings.ensure_leverage's HL half)."""
        action = {'type': 'updateLeverage', 'asset': int(asset),
                  'isCross': bool(is_cross), 'leverage': int(leverage)}
        self._post_action(action)
        return 'set'
