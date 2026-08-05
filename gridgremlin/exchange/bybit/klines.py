# Public kline fetch for the backtest CLI. No keys, no signing — market data.
import json
import urllib.parse
import urllib.request

PUBLIC_HOST = 'https://api-demo.bybit.com'   # public data; demo-phase posture
KLINE_LIMIT = 1000


def parse_kline_rows(rows):
    """The venue returns klines NEWEST FIRST; bars replay oldest first."""
    return [{'t': int(r[0]), 'o': float(r[1]), 'h': float(r[2]),
             'l': float(r[3]), 'c': float(r[4])} for r in reversed(rows)]


def fetch_bars(category, symbol, bar_minutes, start_ms, end_ms):
    bars, cursor = [], start_ms
    step = bar_minutes * 60_000 * KLINE_LIMIT
    while cursor < end_ms:
        q = urllib.parse.urlencode({
            'category': category, 'symbol': symbol,
            'interval': str(bar_minutes), 'start': cursor,
            'end': min(cursor + step, end_ms), 'limit': KLINE_LIMIT})
        with urllib.request.urlopen(f'{PUBLIC_HOST}/v5/market/kline?{q}',
                                    timeout=20) as r:
            bars.extend(parse_kline_rows(json.load(r)['result'].get('list', [])))
        cursor += step
    seen = set()
    out = [b for b in bars if not (b['t'] in seen or seen.add(b['t']))]
    out.sort(key=lambda b: b['t'])
    return out


def fetch_instrument(category, symbol):
    q = urllib.parse.urlencode({'category': category, 'symbol': symbol})
    with urllib.request.urlopen(
            f'{PUBLIC_HOST}/v5/market/instruments-info?{q}', timeout=20) as r:
        return json.load(r)['result']['list'][0]
