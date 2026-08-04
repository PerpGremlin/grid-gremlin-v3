# HL contract maths (SPEC A6's payoff): linear maths inherited UNCHANGED,
# only the rounding rules are HL's — 5 significant figures, 6 - szDecimals
# places, never coarser than 1.
from decimal import Decimal, ROUND_HALF_UP

from ...adapters import LinearAdapter, _d, _fmt

PRICE_SIG_FIGS = 5
MAX_DECIMALS = 6
MIN_NOTIONAL_USD = 10.0


class HLPerpAdapter(LinearAdapter):
    market_type = 'linear'

    def __init__(self, spec):
        super().__init__(spec)
        self.one_way_mode = True
        self.sz_decimals = int(spec.get('sz_decimals', 0))

    def _quantum(self, price):
        exponent = _d(price).adjusted()            # floor(log10)
        sig = Decimal(1).scaleb(exponent - (PRICE_SIG_FIGS - 1))
        dec = Decimal(1).scaleb(-(MAX_DECIMALS - self.sz_decimals))
        return min(max(sig, dec), Decimal(1))

    def _price_dec(self, price):
        q = self._quantum(price)
        return (_d(price) / q).to_integral_value(rounding=ROUND_HALF_UP) * q

    def round_price(self, price):
        return float(self._price_dec(price))

    def fmt_price(self, price):
        return _fmt(self._price_dec(price))
