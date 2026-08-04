# The backtester (SPEC T3). The REAL plan_grid replayed over bars — no second
# engine to drift. Fills require trade-through, never touch; funding is
# modelled; the plan is computed at each bar's open, so only pre-existing
# inventory can exit within the bar (conservative by construction).
from .ladder import plan_grid


def backtest(cfg, adapter, bars, fee_rate=0.0002, funding_rate_hourly=0.0,
             bar_hours=1.0):
    long = cfg['side'] == 'long'
    sign = 1.0 if long else -1.0
    held, basis = 0.0, None
    realized = fees = funding = 0.0
    trips = entry_fills = 0
    peak = max_drawdown = 0.0
    equity_curve = []

    for bar in bars:
        desired = plan_grid(cfg, adapter, bar['o'], held, basis)
        for o in desired:
            if o['side'] == ('Buy' if long else 'Sell'):        # entries
                through = bar['l'] < o['price'] if long else bar['h'] > o['price']
                if through:
                    total = (basis or 0.0) * held + o['price'] * o['qty']
                    held = adapter.round_qty(held + o['qty'])
                    basis = total / held if held else None
                    fees += o['qty'] * o['price'] * fee_rate
                    entry_fills += 1
            else:                                               # exits
                through = bar['h'] > o['price'] if long else bar['l'] < o['price']
                if through and held > 0:
                    qty = min(o['qty'], held)
                    realized += adapter.realised_pnl(
                        basis, o['price'], qty) * (1.0 if long else -1.0)
                    held = adapter.round_qty(held - qty)
                    fees += qty * o['price'] * fee_rate
                    trips += 1
        if held == 0:
            basis = None
        if held and funding_rate_hourly:
            funding += sign * held * bar['c'] * funding_rate_hourly * bar_hours
        unreal = sign * held * (bar['c'] - basis) if basis else 0.0
        equity = realized - fees - funding + unreal
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return {'grid_profit': realized, 'fees': fees, 'funding': funding,
            'net': realized - fees - funding,
            'total': equity_curve[-1] if equity_curve else 0.0,
            'trips': trips, 'entry_fills': entry_fills,
            'held': held, 'basis': basis,
            'max_drawdown': max_drawdown, 'equity_curve': equity_curve}
