# The backtester (SPEC T3). The REAL plan_grid replayed over bars — no second
# engine to drift. Fills require trade-through, never touch; funding is
# modelled; the plan is computed at each bar's open, so only pre-existing
# inventory can exit within the bar (conservative by construction). Entries
# are OPTIMISTIC on coarse bars: every rung the bar trades through fills,
# where the live bot rests only the window (W1) and a fast move skips rungs
# — replay on bars no coarser than the move you are asking about (T6).
import math

from .ladder import plan_grid, slide_offset
from .window import window


def backtest(cfg, adapter, bars, fee_rate=0.0002, funding_rate_hourly=0.0,
             bar_hours=1.0, spread_bps=1.0):
    long = cfg['side'] == 'long'
    sign = 1.0 if long else -1.0
    step = adapter.qty_step
    held_steps = 0            # inventory in integer qty-steps: float
    held, basis = 0.0, None   # subtract-then-floor loses a whole step
    realized = fees = funding = 0.0
    trips = entry_fills = 0
    peak = max_drawdown = 0.0
    equity_curve = []
    offset, slides = 0, 0      # G17/G18: the window over the lattice
    max_held = 0.0             # the deepest inventory the run carried
    # G21 in whole bars: the trigger must still hold at the open of
    # ceil(confirm_seconds / bar) FURTHER bars — a one-bar spike never slides
    s = cfg.get('slide') or {}
    confirm_bars = math.ceil((s.get('confirm_seconds') or 0.0)
                             / (bar_hours * 3600.0))
    beyond = 0

    for bar in bars:
        new = slide_offset(cfg, offset, bar['o'])
        if new == offset:
            beyond = 0
        else:
            beyond += 1
            if beyond > confirm_bars:
                offset, slides, beyond = new, slides + 1, 0
        # a synthetic spread around the open feeds B3/B4: without bid/ask
        # the guard-band drops never happened and near-quote rungs filled
        # that live would skip — optimistic (audit 2026-08-07 LOW)
        half = bar['o'] * spread_bps / 20_000.0
        desired = plan_grid(cfg, adapter, bar['o'], held, basis,
                            bar['o'] - half, bar['o'] + half, offset=offset)
        # T6/W1: only what the live bot would have RESTING can fill
        desired = window(desired, bar['o'], cfg.get('place_within_pct', 0.05))
        for o in desired:
            if o['side'] == ('Buy' if long else 'Sell'):        # entries
                through = bar['l'] < o['price'] if long else bar['h'] > o['price']
                if through:
                    total = (basis or 0.0) * held + o['price'] * o['qty']
                    held_steps += int(round(o['qty'] / step))
                    held = held_steps * step
                    basis = total / held if held else None
                    fees += o['qty'] * o['price'] * fee_rate
                    entry_fills += 1
            else:                                               # exits
                through = bar['h'] > o['price'] if long else bar['l'] < o['price']
                if through and held > 0:
                    qty_steps = min(int(round(o['qty'] / step)), held_steps)
                    qty = qty_steps * step
                    realized += adapter.realised_pnl(
                        basis, o['price'], qty) * (1.0 if long else -1.0)
                    held_steps -= qty_steps
                    held = held_steps * step
                    fees += qty * o['price'] * fee_rate
                    trips += 1
        if held_steps == 0:
            held, basis = 0.0, None
        max_held = max(max_held, held)
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
            'max_drawdown': max_drawdown, 'equity_curve': equity_curve,
            'slides': slides, 'offset': offset, 'max_held': max_held}
