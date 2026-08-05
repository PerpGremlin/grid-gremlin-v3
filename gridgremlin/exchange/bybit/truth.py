# Bybit truth (SPEC V1-V5, E5, I4). Pure reads; the schema is shared (../truth).
from ..errors import VenueError
from ..truth import (ORDER_KEYS, POSITION_KEYS, TRUTH_KEYS, WALLET_KEYS,
                     TruthError, _f, validate_truth, validate_wallet)

MAX_ORDER_PAGES = 500     # E5 backstop: hitting it is an error, not a bound


def parse_instrument(category, info):
    """A1's venue half: instruments-info -> the adapter spec dict."""
    lot = info.get('lotSizeFilter', {})
    spec = {'symbol': info['symbol'],
            'price_tick': _f(info.get('priceFilter', {}).get('tickSize')),
            'qty_step': _f(lot.get('qtyStep') or lot.get('basePrecision')),
            'min_qty': _f(lot.get('minOrderQty') or lot.get('basePrecision')),
            'min_notional': _f(lot.get('minNotionalValue')
                               or lot.get('minOrderAmt')),
            'settle_coin': info.get('settleCoin'),
            'base_coin': info.get('baseCoin'),
            'funding_interval_minutes': _f(info.get('fundingInterval'), 480.0)}
    if info.get('status') != 'Trading':
        raise VenueError(f"{info['symbol']}: status {info.get('status')!r}")
    return spec


def read_wallet(result):
    """One shape always — the empty account is not a second schema."""
    rows = result.get('list') or [{}]
    acct = rows[0]
    coins = {c['coin']: {'wallet_balance': _f(c.get('walletBalance'), 0.0),
                         'equity': _f(c.get('equity'), 0.0),
                         'available': _f(c.get('availableToWithdraw'), 0.0)}
             for c in acct.get('coin', [])}
    return validate_wallet({
        'equity': _f(acct.get('totalEquity'), 0.0),
        'available': _f(acct.get('totalAvailableBalance'), 0.0),
        'mm_rate': _f(acct.get('accountMMRate')),
        'im_rate': _f(acct.get('accountIMRate')),
        'maint_margin': _f(acct.get('totalMaintenanceMargin')),
        'coins': coins})


def read_positions(result):
    """One shape always: every key present, None where the venue is silent."""
    out = {}
    for p in result.get('list', []):
        size = _f(p.get('size'), 0.0)
        if size == 0:
            continue
        idx = int(p.get('positionIdx') or 0)
        out[idx] = {'position_idx': idx,
                    'side': p.get('side') or None,
                    'size': size,
                    'avg_entry': _f(p.get('avgPrice')) or None,
                    'liq_price': _f(p.get('liqPrice')) or None,
                    'stop_loss': _f(p.get('stopLoss')) or None,
                    'take_profit': _f(p.get('takeProfit')) or None,
                    'leverage': _f(p.get('leverage')),
                    'unrealised_pnl': _f(p.get('unrealisedPnl'))}
    return out


def read_orders(client, category, symbol):
    """E5: follow the cursor to the end or raise — a partial book instructs
    the writer to duplicate. V5: trigger orders are excluded."""
    orders, cursor = [], None
    for _ in range(MAX_ORDER_PAGES):
        page = client.open_orders_page(category, symbol, cursor)
        for o in page.get('list', []):
            if o.get('stopOrderType'):
                continue
            orders.append({'order_id': o.get('orderId'),
                           'link_id': o.get('orderLinkId') or '',
                           'side': o.get('side'),
                           'price': _f(o.get('price')),
                           'qty': _f(o.get('qty')),
                           'cum_exec_qty': _f(o.get('cumExecQty'), 0.0),
                           'reduce_only': bool(o.get('reduceOnly')),
                           'status': o.get('orderStatus'),
                           'position_idx': int(o.get('positionIdx') or 0),
                           'order_type': o.get('orderType'),
                           'updated_time_ms': int(o.get('updatedTime') or 0)})
        cursor = page.get('nextPageCursor')
        if not cursor:
            return orders
    raise VenueError(f'{symbol}: order book beyond {MAX_ORDER_PAGES} pages',
                     kind='partial_read')


def read_spot_position(wallet, base_coin, dust=0.0):
    """V6: spot's 'position' is the wallet's base-coin holding, synthesized
    into the one position shape. The venue keeps no basis: avg_entry is None
    and the adoption family runs ref-only (G6's no-basis arm) unless the
    config states `assumed_avg_entry`. A residue below `dust` (the venue's
    min order qty) is FLAT — spot fees settle in the base coin, so a full
    exit leaves an unsellable shaving that must never count as holding.
    D24: the balance is SIGNED — a borrow-short lives as a negative balance,
    so sign is side and the dust rule applies symmetrically around zero."""
    coin = wallet['coins'].get(base_coin) or {}
    size = coin.get('wallet_balance', 0.0)
    if abs(size) < dust or size == 0:
        return {}
    return {0: {'position_idx': 0,
                'side': 'Buy' if size > 0 else 'Sell',   # D24: negative = short
                'size': abs(size),
                'avg_entry': None, 'liq_price': None, 'stop_loss': None,
                'take_profit': None, 'leverage': None,
                'unrealised_pnl': None}}


def read_symbol_truth(client, market_type, symbol, funding_interval_minutes=480.0,
                      base_coin=None, dust=0.0):
    """V1/V2: the one truth shape; funding normalised to per-hour at read.
    V6: spot has no position endpoint — the wallet holding is the position."""
    t = client.tickers(market_type, symbol)
    mark = _f(t.get('markPrice')) or _f(t.get('lastPrice'))
    bid, ask = _f(t.get('bid1Price')), _f(t.get('ask1Price'))
    rate = _f(t.get('fundingRate'))
    hours = max(funding_interval_minutes, 1.0) / 60.0
    if market_type == 'spot':
        if not base_coin:
            raise TruthError(f'{symbol}: spot truth needs base_coin — refuse, '
                             'never guess (E8)')
        positions = read_spot_position(read_wallet(client.wallet_balance()),
                                       base_coin, dust=dust)
    else:
        positions = read_positions(client.position_list(market_type, symbol))
    return validate_truth({
        'symbol': symbol,
        'market_type': market_type,
        'mark': mark,
        'bid': bid,
        'ask': ask,
        'split_ref': (bid + ask) / 2.0 if bid and ask else mark,
        'funding_rate_hourly': rate / hours if rate is not None else None,
        'next_funding_time_ms': int(t.get('nextFundingTime') or 0) or None,
        'orders': read_orders(client, market_type, symbol),
        'positions': positions})


def dedup_executions(seen_exec_ids, executions):
    """I4: fills deduplicate by venue execution id, across restarts — the
    caller persists nothing; `seen_exec_ids` lives and dies with the process,
    and replays are harmless because the set is rebuilt from this same read."""
    fresh = []
    for e in executions:
        eid = e.get('execId')
        if eid and eid not in seen_exec_ids:
            seen_exec_ids.add(eid)
            fresh.append(e)
    return fresh


SEVEN_DAYS_MS = 7 * 24 * 3600 * 1000      # the venue's max span per query


def read_fills(client, category, symbol, start_ms, end_ms):
    """R1: history in 7-day windows, each cursor followed to the end or
    refused (E5); only execType Trade — funding and settlement rows never
    enter the fill ledger. Deduped by execution id (I4)."""
    fills, seen = [], set()
    win_start, end_ms = int(start_ms), int(end_ms)
    while win_start < end_ms:
        win_end = min(win_start + SEVEN_DAYS_MS, end_ms)
        cursor = None
        for _ in range(MAX_ORDER_PAGES):
            page = client.executions_page(category, symbol, win_start,
                                          win_end, cursor)
            for e in page.get('list', []):
                eid = e.get('execId')
                if e.get('execType') != 'Trade' or not eid or eid in seen:
                    continue
                seen.add(eid)
                fills.append({'exec_id': eid,
                              'time_ms': int(e.get('execTime') or 0),
                              'symbol': e.get('symbol'),
                              'side': 'buy' if e.get('side') == 'Buy'
                              else 'sell',
                              'price': _f(e.get('execPrice')),
                              'qty': _f(e.get('execQty'), 0.0),
                              'fee': _f(e.get('execFee'), 0.0),
                              'link_id': e.get('orderLinkId') or ''})
            cursor = page.get('nextPageCursor')
            if not cursor:
                break
        else:
            raise VenueError(f'{symbol}: execution history beyond '
                             f'{MAX_ORDER_PAGES} pages', kind='partial_read')
        win_start = win_end
    fills.sort(key=lambda f: f['time_ms'])
    return fills
