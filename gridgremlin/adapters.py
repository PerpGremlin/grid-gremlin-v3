# Contract maths (SPEC A1-A6). Pure — no I/O, no network, no clock.
#
# An adapter is built from a spec dict the venue reported (A1); config never
# declares instrument facts. Quantity rounding always FLOORS — never place more
# than intended (A2). One placeable predicate folds the venue minimums (A3).
# Inverse PnL is base-coin and is never summed with quote PnL (A4) — v1 once
# booked +$396k on a $100 position by getting this wrong. positionIdx derives
# jointly from (order side, reduce_only) (A5). The registry is the venue seam:
# a second venue adds a spec-fetcher, not a fork (A6).

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

MARKET_TYPES = ('linear', 'inverse', 'spot')
REQUIRED_SPEC_FIELDS = ('symbol', 'qty_step', 'price_tick', 'min_qty')


class InstrumentError(ValueError):
    """A spec the adapter cannot safely trade from — refuse at setup."""


def _d(x):
    """Decimal via str() so float repr never leaks into venue arithmetic."""
    return Decimal(str(x))


def _floor_to_step(value, step):
    if step == 0:
        return _d(value)
    v, s = _d(value), _d(step)
    return (v / s).to_integral_value(rounding=ROUND_DOWN) * s


def _round_to_step(value, step):
    if step == 0:
        return _d(value)
    v, s = _d(value), _d(step)
    return (v / s).to_integral_value(rounding=ROUND_HALF_UP) * s


def _fmt(dec):
    """Exchange-ready plain string: no scientific notation, no trailing junk."""
    s = format(dec.normalize(), 'f')
    return s


class _Adapter:
    """Per-instrument contract maths. Never constructed from config (A1)."""

    market_type = None       # overridden per class
    supports_short = True
    reports_avg_entry = True

    def __init__(self, spec):
        missing = [f for f in REQUIRED_SPEC_FIELDS if spec.get(f) in (None, 0, '')]
        if missing:
            raise InstrumentError(
                f"instrument spec for {spec.get('symbol', '?')} is missing "
                f'{missing} — refuse, never guess (A1)')
        self.symbol = spec['symbol']
        self.qty_step = float(spec['qty_step'])
        self.price_tick = float(spec['price_tick'])
        self.min_qty = float(spec['min_qty'])
        self.min_notional = (float(spec['min_notional'])
                             if spec.get('min_notional') is not None else None)
        self.settle_coin = spec.get('settle_coin')
        self.one_way_mode = bool(spec.get('one_way_mode', False))

    # --- rounding (A2) -------------------------------------------------------

    def round_price(self, price):
        return float(_round_to_step(price, self.price_tick))

    def round_qty(self, qty):
        """Floors. A grid must never place MORE than it intended."""
        return float(_floor_to_step(qty, self.qty_step))

    def fmt_price(self, price):
        return _fmt(_round_to_step(price, self.price_tick))

    def fmt_qty(self, qty):
        return _fmt(_floor_to_step(qty, self.qty_step))

    # --- minimums (A3) -------------------------------------------------------

    def meets_minimum(self, qty, price):
        if qty < self.min_qty:
            return False
        if self.min_notional is not None and qty * price < self.min_notional:
            return False
        return True

    # --- money (A4) ----------------------------------------------------------

    def qty_from_notional(self, notional, price):
        raise NotImplementedError

    def realised_pnl(self, entry, exit_price, qty):
        """In the SETTLE coin — quote for linear/spot, base for inverse."""
        raise NotImplementedError

    def pnl_to_usd(self, pnl, price):
        raise NotImplementedError

    # --- position identity (A5) ----------------------------------------------

    def position_idx(self, order_side, reduce_only):
        raise NotImplementedError


class LinearAdapter(_Adapter):
    """USDT and USDC perps are ONE adapter — settle coin is data, not a fork."""

    market_type = 'linear'

    def qty_from_notional(self, notional, price):
        return notional / price

    def realised_pnl(self, entry, exit_price, qty):
        return (exit_price - entry) * qty          # quote (settle) coin

    def pnl_to_usd(self, pnl, price):
        return pnl                                  # already quote-denominated

    def position_idx(self, order_side, reduce_only):
        if self.one_way_mode:
            return 0
        opening_long = (order_side == 'Buy') != bool(reduce_only)
        return 1 if opening_long else 2


class InverseAdapter(_Adapter):
    """Coin-settled: qty is USD contracts, PnL is BASE coin (A4)."""

    market_type = 'inverse'

    def __init__(self, spec):
        super().__init__(spec)
        self.one_way_mode = True                    # inverse holds one side

    def qty_from_notional(self, notional, price):
        return notional                             # 1 contract = $1, price-free

    def realised_pnl(self, entry, exit_price, qty):
        return qty * (1.0 / entry - 1.0 / exit_price)   # BASE coin

    def pnl_to_usd(self, pnl, price):
        return pnl * price

    def position_idx(self, order_side, reduce_only):
        return 0


class SpotAdapter(_Adapter):
    """A holding: long only, no positionIdx, no reduce_only, no venue basis."""

    market_type = 'spot'
    supports_short = False
    reports_avg_entry = False

    def __init__(self, spec):
        super().__init__(spec)
        self.one_way_mode = True

    def qty_from_notional(self, notional, price):
        return notional / price

    def realised_pnl(self, entry, exit_price, qty):
        return (exit_price - entry) * qty

    def pnl_to_usd(self, pnl, price):
        return pnl

    def position_idx(self, order_side, reduce_only):
        return None


ADAPTERS = {cls.market_type: cls
            for cls in (LinearAdapter, InverseAdapter, SpotAdapter)}


def adapter_for(market_type, spec):
    """The seam (A6): venues fetch specs; this chooses the maths."""
    if market_type not in ADAPTERS:
        raise InstrumentError(f"no adapter for market_type '{market_type}' — "
                              f'one of {tuple(ADAPTERS)}')
    return ADAPTERS[market_type](spec)
