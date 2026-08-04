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


NOT_MODIFIED_CODES = {110025, 110043, 34040}
CANNOT_MODIFY_CODES = {110024, 110028}
RO_CAPACITY_CODES = {110017}
MARGIN_CODES = {110004, 110006, 110007, 110012, 110044, 110045, 110052, 170131}


def _post_kind(ret_code):
    if ret_code in NOT_MODIFIED_CODES:
        return 'not_modified'
    if ret_code in CANNOT_MODIFY_CODES:
        return 'cannot_modify'
    if ret_code in RO_CAPACITY_CODES:
        return 'ro_capacity'
    if ret_code in MARGIN_CODES:
        return 'margin'
    if ret_code in ORDER_GONE_CODES:
        return 'gone'
    if ret_code in RATE_LIMIT_CODES:
        return 'rate_limit'
    return 'other'


class WriteClient(Client):
    """The write surface. Every order is post-only (G13's venue backstop)."""

    def post(self, path, body):
        if not self._synced:
            self._sync_clock()
        ts = self._ts()
        payload = json.dumps(body)
        headers = {'X-BAPI-API-KEY': self.api_key,
                   'X-BAPI-TIMESTAMP': ts,
                   'X-BAPI-RECV-WINDOW': RECV_WINDOW,
                   'X-BAPI-SIGN': self._sign(ts, payload),
                   'Content-Type': 'application/json'}
        req = urllib.request.Request(self.base + path, data=payload.encode(),
                                     headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        code = int(data.get('retCode', -1))
        if code in NOT_MODIFIED_CODES or code == 0:
            return data.get('result', {})
        raise VenueError(f"bybit {path}: retCode {code}: {data.get('retMsg')}",
                         kind=_post_kind(code))

    def place_order(self, category, symbol, side, qty, price, link_id,
                    position_idx=0, reduce_only=False):
        return self.post('/v5/order/create', {
            'category': category, 'symbol': symbol, 'side': side,
            'orderType': 'Limit', 'timeInForce': 'PostOnly', 'qty': qty,
            'price': price, 'orderLinkId': link_id,
            'positionIdx': position_idx, 'reduceOnly': reduce_only})

    def cancel_order(self, category, symbol, order_id):
        return self.post('/v5/order/cancel', {'category': category,
                                              'symbol': symbol,
                                              'orderId': order_id})

    def amend_order(self, category, symbol, order_id, qty):
        return self.post('/v5/order/amend', {'category': category,
                                             'symbol': symbol,
                                             'orderId': order_id, 'qty': qty})

    def ensure_hedge_mode(self, category, symbol):
        try:
            self.post('/v5/position/switch-mode',
                      {'category': category, 'symbol': symbol, 'mode': 3})
        except VenueError as e:
            if e.kind not in ('not_modified', 'cannot_modify'):
                raise

    def risk_limit_tiers(self, category, symbol):
        r = self.get('/v5/market/risk-limit',
                     {'category': category, 'symbol': symbol})
        return [{'id': int(t['id']), 'limit': float(t['riskLimitValue']),
                 'mm_rate': float(t['maintenanceMargin']),
                 'max_leverage': float(t.get('maxLeverage', 0))}
                for t in r['list']]

    def set_risk_limit(self, category, symbol, risk_id, position_idx):
        self.post('/v5/position/set-risk-limit',
                  {'category': category, 'symbol': symbol, 'riskId': risk_id,
                   'positionIdx': position_idx})

    def set_leverage(self, category, symbol, leverage):
        try:
            self.post('/v5/position/set-leverage',
                      {'category': category, 'symbol': symbol,
                       'buyLeverage': str(leverage),
                       'sellLeverage': str(leverage)})
        except VenueError as e:
            if e.kind != 'not_modified':
                raise
