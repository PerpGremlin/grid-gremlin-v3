# Bybit v5 REST reads (SPEC V, E5, E8). Writes land with the applying slices.
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request

from ..errors import VenueError

BASE_URLS = {'demo': 'https://api-demo.bybit.com',
             'testnet': 'https://api-testnet.bybit.com',
             'mainnet': 'https://api.bybit.com'}
RECV_WINDOW = '15000'
RATE_LIMIT_CODES = {10006, 10018, 10429, 429}
ORDER_GONE_CODES = {110001, 170213}
CLOCK_CODE = 10002


def detect_env():
    if os.environ.get('BYBIT_DEMO', '').lower() == 'true':
        return 'demo'
    if os.environ.get('BYBIT_TESTNET', '').lower() == 'true':
        return 'testnet'
    return 'mainnet'


def _kind(ret_code):
    if ret_code in RATE_LIMIT_CODES:
        return 'rate_limit'
    if ret_code in ORDER_GONE_CODES:
        return 'gone'
    return 'other'


class Client:
    """E8: constructing or reading never guesses — failures raise."""

    def __init__(self, env=None, api_key=None, api_secret=None, transport=None):
        self.env = env or detect_env()
        self.base = BASE_URLS[self.env]
        self.api_key = api_key or os.environ.get('BYBIT_API_KEY', '')
        self.api_secret = api_secret or os.environ.get('BYBIT_API_SECRET', '')
        self._transport = transport or self._http
        self._offset_ms = 0
        self._synced = False

    # --- transport -----------------------------------------------------------

    def _http(self, url, headers):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def _ts(self):
        return str(int(time.time() * 1000) + self._offset_ms)

    def _sync_clock(self):
        data = self._transport(self.base + '/v5/market/time', {})
        server_ms = int(data['result']['timeSecond']) * 1000
        self._offset_ms = server_ms - int(time.time() * 1000)
        self._synced = True

    def _sign(self, ts, query):
        payload = ts + self.api_key + RECV_WINDOW + query
        return hmac.new(self.api_secret.encode(), payload.encode(),
                        hashlib.sha256).hexdigest()

    def get(self, path, params=None, signed=False, _retried=False):
        query = urllib.parse.urlencode(sorted((params or {}).items()))
        headers = {}
        if signed:
            if not self._synced:
                self._sync_clock()
            ts = self._ts()
            headers = {'X-BAPI-API-KEY': self.api_key,
                       'X-BAPI-TIMESTAMP': ts,
                       'X-BAPI-RECV-WINDOW': RECV_WINDOW,
                       'X-BAPI-SIGN': self._sign(ts, query)}
        url = self.base + path + ('?' + query if query else '')
        data = self._transport(url, headers)
        code = int(data.get('retCode', -1))
        if code == 0:
            return data['result']
        if code == CLOCK_CODE and not _retried:
            self._sync_clock()
            return self.get(path, params, signed, _retried=True)
        raise VenueError(f"bybit {path}: retCode {code}: {data.get('retMsg')}",
                         kind=_kind(code))

    # --- reads ---------------------------------------------------------------

    def tickers(self, category, symbol):
        r = self.get('/v5/market/tickers',
                     {'category': category, 'symbol': symbol})
        return r['list'][0]

    def instruments_info(self, category, symbol):
        r = self.get('/v5/market/instruments-info',
                     {'category': category, 'symbol': symbol})
        if not r['list']:
            raise VenueError(f'{symbol}: unknown instrument ({category})')
        return r['list'][0]

    def wallet_balance(self):
        return self.get('/v5/account/wallet-balance',
                        {'accountType': 'UNIFIED'}, signed=True)

    def position_list(self, category, symbol):
        return self.get('/v5/position/list',
                        {'category': category, 'symbol': symbol}, signed=True)

    def open_orders_page(self, category, symbol, cursor=None):
        params = {'category': category, 'symbol': symbol, 'limit': 50}
        if cursor:
            params['cursor'] = cursor
        return self.get('/v5/order/realtime', params, signed=True)

    def executions(self, category, symbol, limit=50):
        return self.get('/v5/execution/list',
                        {'category': category, 'symbol': symbol,
                         'limit': limit}, signed=True)
