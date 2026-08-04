# HL info client (reads only; writes arrive with promotion, keys stay in v2).
import json
import os
import urllib.error
import urllib.request

from ..errors import VenueError

BASE_URLS = {'mainnet': 'https://api.hyperliquid.xyz',
             'testnet': 'https://api.hyperliquid-testnet.xyz'}


class HLError(VenueError):
    def __init__(self, status, msg, body=None, ambiguous=False, kind='other'):
        super().__init__(msg, kind=kind, ambiguous=ambiguous)
        self.status = status
        self.body = body or ''


def detect_env():
    if os.environ.get('HL_TESTNET', '').lower() == 'true':
        return 'testnet'
    return 'mainnet'


class InfoClient:
    def __init__(self, env=None, address=None, transport=None):
        self.env = env or detect_env()
        if self.env == 'mainnet':
            raise VenueError("v3's HL phase is testnet-only — the owner's live "
                             'account stays untouched (F5, owner 2026-08-04)')
        self.base = BASE_URLS[self.env]
        self.address = address or os.environ.get('HL_ACCOUNT_ADDRESS', '')
        self._transport = transport or self._http

    def _http(self, body):
        req = urllib.request.Request(self.base + '/info',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def _user(self):
        if not self.address:
            raise VenueError('HL_ACCOUNT_ADDRESS is not set — refuse, never '
                             'guess (E8)')
        return self.address

    def meta(self):
        return self._transport({'type': 'meta'})

    def meta_and_ctxs(self):
        return self._transport({'type': 'metaAndAssetCtxs'})

    def l2_book(self, coin):
        return self._transport({'type': 'l2Book', 'coin': coin})

    def clearinghouse_state(self):
        return self._transport({'type': 'clearinghouseState',
                                'user': self._user()})

    def open_orders(self, coin=None):
        return self._transport({'type': 'frontendOpenOrders',
                                'user': self._user()})

    def user_abstraction(self):
        return self._transport({'type': 'userAbstraction',
                                'user': self._user()})

    def spot_clearinghouse_state(self):
        return self._transport({'type': 'spotClearinghouseState',
                                'user': self._user()})

    def _post(self, path, body, retry_429=True):
        """The write transport (stub point for specs)."""
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors='replace')[:300]
            if e.code == 429 and retry_429:
                import time as _t
                _t.sleep(2.0)
                return self._post(path, body, retry_429=False)
            raise HLError(e.code, f'{path}: HTTP {e.code}: {text}', text,
                          kind='rate_limit' if e.code == 429 else 'other')
