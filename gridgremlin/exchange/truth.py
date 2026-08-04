# The truth contract, venue-neutral (SPEC V1). One schema, every venue.
TRUTH_KEYS = ('symbol', 'market_type', 'mark', 'bid', 'ask', 'split_ref',
              'funding_rate_hourly', 'next_funding_time_ms', 'orders',
              'positions')
ORDER_KEYS = ('order_id', 'link_id', 'side', 'price', 'qty', 'cum_exec_qty',
              'reduce_only', 'status', 'position_idx', 'order_type',
              'updated_time_ms')
POSITION_KEYS = ('position_idx', 'side', 'size', 'avg_entry', 'liq_price',
                 'stop_loss', 'take_profit', 'leverage', 'unrealised_pnl')
WALLET_KEYS = ('equity', 'available', 'mm_rate', 'im_rate', 'maint_margin',
               'coins')


class TruthError(ValueError):
    """V1: a shape the engine must not trade from."""


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _require(d, keys, what):
    missing = [k for k in keys if k not in d]
    if missing:
        raise TruthError(f'{what} missing {missing}')


def validate_truth(t):
    _require(t, TRUTH_KEYS, 'truth')
    for o in t['orders']:
        _require(o, ORDER_KEYS, 'order')
    for p in t['positions'].values():
        _require(p, POSITION_KEYS, 'position')
    return t


def validate_wallet(w):
    _require(w, WALLET_KEYS, 'wallet')
    return w
