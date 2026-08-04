# HL truth (SPEC V1-V5): the SAME schema, built from HL's answers. Funding is
# hourly at the source, so the per-hour normalisation is an identity here —
# the unit trap between venues (exchange study M16) dies in the field name.
from ..errors import VenueError
from ..truth import _f, validate_truth, validate_wallet

FUNDING_INTERVAL_MINUTES = 60.0


def parse_instrument(entry):
    """A1's venue half. price_tick is the DECIMALS cap, not the binding rule —
    HL prices round by significant figures (see adapters)."""
    if entry.get('isDelisted'):
        raise VenueError(f"{entry['name']}: delisted")
    sz = int(entry.get('szDecimals', 0))
    step = 10.0 ** -sz
    return {'symbol': entry['name'], 'qty_step': step, 'min_qty': step,
            'price_tick': 10.0 ** -(6 - sz), 'min_notional': 10.0,
            'settle_coin': 'USDC', 'sz_decimals': sz,
            'funding_interval_minutes': FUNDING_INTERVAL_MINUTES}


def read_wallet(state):
    summary = state.get('marginSummary', {})
    equity = _f(summary.get('accountValue'), 0.0)
    maint = _f(state.get('crossMaintenanceMarginUsed'), 0.0)
    used = _f(summary.get('totalMarginUsed'), 0.0)
    return validate_wallet({
        'equity': equity,
        'available': _f(state.get('withdrawable'), 0.0),
        'mm_rate': maint / equity if equity else None,      # computed, not sent
        'im_rate': used / equity if equity else None,
        'maint_margin': maint,
        'coins': {'USDC': {'wallet_balance': equity, 'equity': equity,
                           'available': _f(state.get('withdrawable'), 0.0)}}})


def read_positions(state, coin):
    """One shape, every key. stop_loss is always None on HL — trigger orders
    are not a position field here — which is exactly why watch: position_sl
    documents itself as inert on this venue."""
    out = {}
    for ap in state.get('assetPositions', []):
        p = ap.get('position', {})
        if p.get('coin') != coin:
            continue
        szi = _f(p.get('szi'), 0.0)
        if not szi:
            continue
        out[0] = {'position_idx': 0,
                  'side': 'Buy' if szi > 0 else 'Sell',
                  'size': abs(szi),
                  'avg_entry': _f(p.get('entryPx')) or None,
                  'liq_price': _f(p.get('liquidationPx')) or None,
                  'stop_loss': None,
                  'take_profit': None,
                  'leverage': _f((p.get('leverage') or {}).get('value')),
                  'unrealised_pnl': _f(p.get('unrealizedPnl'))}
    return out


def read_orders(raw, coin):
    """V5: trigger orders excluded. HL's sz is the REMAINDER; qty is origSz."""
    out = []
    for o in raw:
        if o.get('coin') != coin or o.get('isTrigger'):
            continue
        orig = _f(o.get('origSz'), 0.0)
        left = _f(o.get('sz'), 0.0)
        out.append({'order_id': str(o.get('oid')),
                    'link_id': o.get('cloid') or '',
                    'side': 'Buy' if o.get('side') == 'B' else 'Sell',
                    'price': _f(o.get('limitPx')),
                    'qty': orig,
                    'cum_exec_qty': max(orig - left, 0.0),
                    'reduce_only': bool(o.get('reduceOnly')),
                    'status': 'PartiallyFilled' if left < orig else 'New',
                    'position_idx': 0,
                    'order_type': o.get('orderType', 'Limit'),
                    'updated_time_ms': int(o.get('timestamp') or 0)})
    return out


def read_symbol_truth(client, coin):
    meta, ctxs = client.meta_and_ctxs()
    names = [e['name'] for e in meta['universe']]
    if coin not in names:
        raise VenueError(f'{coin}: not in the HL universe')
    ctx = ctxs[names.index(coin)]           # positional pairing, perps only
    book = client.l2_book(coin)
    bids, asks = book.get('levels', [[], []])
    bid = _f(bids[0]['px']) if bids else None
    ask = _f(asks[0]['px']) if asks else None
    mark = _f(ctx.get('markPx'))
    return validate_truth({
        'symbol': coin,
        'market_type': 'linear',
        'mark': mark,
        'bid': bid,
        'ask': ask,
        'split_ref': (bid + ask) / 2.0 if bid and ask else mark,
        'funding_rate_hourly': _f(ctx.get('funding')),      # hourly at source
        'next_funding_time_ms': None,
        'orders': read_orders(client.open_orders(coin), coin),
        'positions': read_positions(client.clearinghouse_state(), coin)})
