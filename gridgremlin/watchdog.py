# The watchdog (SPEC F1-F6). Pure evaluate/decide; the CLI pages before it
# persists, so a failed page re-pages.
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import ConfigError, _flag, _num, _reject_unknown
from .exchange.env import load_env

WATCHDOG_KEYS = ('tag', 'snapshot', 'state', 'staleness_seconds', 'mm_rate_max',
                 'equity_min', 'equity_drawdown_max', 're_alert_seconds',
                 'positions', 'assumes_sole_actor')


def validate_watchdog(cfg, where='watchdog'):
    """v2 shipped no validator for these; v3 refuses like everything else."""
    _reject_unknown(cfg, WATCHDOG_KEYS, where)
    out = {k: v for k, v in cfg.items() if not k.startswith('_')}
    for key in ('tag', 'snapshot', 'state'):
        if not isinstance(out.get(key), str) or not out.get(key):
            raise ConfigError(f"{where}: '{key}' is required")
    out['staleness_seconds'] = _num(out, 'staleness_seconds', where,
                                    least=0.0, least_open=True, required=True)
    out['mm_rate_max'] = _num(out, 'mm_rate_max', where, least=0.0,
                              least_open=True, most=1.0, required=True)
    out['equity_min'] = _num(out, 'equity_min', where, least=1.0, required=True)
    out['equity_drawdown_max'] = _num(out, 'equity_drawdown_max', where,
                                      least=0.0, least_open=True, most=1.0)
    out['re_alert_seconds'] = _num(out, 're_alert_seconds', where, least=0.0,
                                   least_open=True, required=True)
    if 'assumes_sole_actor' not in cfg:
        raise ConfigError(f"{where}: 'assumes_sole_actor' is required — every "
                          'threshold assumes something about who else trades '
                          'this account; say it (F6)')
    out['assumes_sole_actor'] = _flag(out, 'assumes_sole_actor')
    positions = out.get('positions')
    if not isinstance(positions, dict) or not positions:
        raise ConfigError(f"{where}: 'positions' must map every botid to "
                          '{min, max} (F1)')
    for botid, lim in positions.items():
        if not isinstance(lim, dict) or 'min' not in lim or 'max' not in lim:
            raise ConfigError(f'{where}: positions.{botid} needs min and max')
    return out


def peak_equity(prev, equity):
    """Monotone high-water. None is unknown, never a zero — v2's falsy
    sentinel silently disabled the drawdown check (exchange study M30)."""
    if equity is None:
        return prev
    if prev is None:
        return equity
    return max(prev, equity)


def evaluate(cfg, row, now, peak):
    """Pure: one snapshot row -> {stable_key: human_text}."""
    if row is None:
        return {'nosnap': 'no readable snapshot row'}
    breaches = {}
    age = now - row['t']
    if age > cfg['staleness_seconds']:
        breaches['stale'] = f'snapshot is {age:.0f}s old'
    if row.get('mm_rate') is not None and row['mm_rate'] > cfg['mm_rate_max']:
        breaches['mmr'] = f"mm_rate {row['mm_rate']:.4f} > {cfg['mm_rate_max']}"
    if row['equity'] < cfg['equity_min']:
        breaches['equity'] = f"equity {row['equity']:.0f} < {cfg['equity_min']:.0f}"
    dd_max = cfg.get('equity_drawdown_max')
    if dd_max and peak:
        dd = (peak - row['equity']) / peak
        if dd > dd_max:
            breaches['drawdown'] = f'{dd:.1%} below the peak'
    for botid, lim in cfg['positions'].items():
        bot = row['bots'].get(botid)
        if bot is None:
            breaches[f'missing:{botid}'] = 'absent from the snapshot entirely'
            continue
        size = abs(bot['position'])
        if not lim['min'] <= size <= lim['max']:
            breaches[f'pos:{botid}'] = (f"position {size:.10g} outside "
                                        f"[{lim['min']:.10g}, {lim['max']:.10g}]")
    return breaches


def decide(state, breaches, now, re_alert_seconds):
    """Pure transitions: page new keys, remind persisting ones on the
    interval, announce recoveries. Returns (pages, new_state)."""
    pages, new_state = [], {}
    for key, text in breaches.items():
        last = state.get(key)
        if last is None:
            pages.append(f'{key}: {text}')
            new_state[key] = now
        elif now - last >= re_alert_seconds:
            pages.append(f'still breached — {key}: {text}')
            new_state[key] = now
        else:
            new_state[key] = last
    for key in state:
        if key not in breaches:
            pages.append(f'recovered: {key}')
    return pages, new_state


def send_telegram(text):
    """Direct page — the watchdog is its own process; a send failure RAISES so
    state is never persisted over an undelivered page (it re-pages next tick,
    and the unit's OnFailure alarm fires)."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not (token and chat):
        return
    data = urllib.parse.urlencode({'chat_id': chat, 'text': text}).encode()
    urllib.request.urlopen(
        f'https://api.telegram.org/bot{token}/sendMessage', data,
        timeout=20).read()


def main(argv):
    load_env()
    cfg = validate_watchdog(json.loads(Path(argv[0]).read_text()))
    now = time.time()
    row = None
    snap = Path(cfg['snapshot'])
    if snap.exists():
        lines = snap.read_text().strip().splitlines()
        if lines:
            try:
                row = json.loads(lines[-1])
            except ValueError:
                row = None
    statep = Path(cfg['state'])
    state = json.loads(statep.read_text()) if statep.exists() else {}
    peak = peak_equity(state.get('_peak'), row['equity'] if row else None)
    breaches = evaluate(cfg, row, now, peak)
    pages, new_alerts = decide(state.get('_alerts', {}), breaches, now,
                               cfg['re_alert_seconds'])
    for page in pages:                       # page BEFORE persisting: a failed
        print(f"[{cfg['tag']}] {page}", flush=True)   # page re-pages next tick
    if pages:
        send_telegram(f"[{cfg['tag']}] " + '\n'.join(pages))
    statep.write_text(json.dumps({'_peak': peak, '_alerts': new_alerts}))
    print(f"[{cfg['tag']}] {'BREACHED' if breaches else 'ok'} "
          f'({len(breaches)} breach(es))', flush=True)
    return 1 if breaches else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
