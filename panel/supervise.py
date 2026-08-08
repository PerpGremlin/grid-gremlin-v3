"""The supervisor (docs/DASHBOARD.md §13): systemd's laptop twin.

Spawns the engine as a fully detached child, stops it with SIGTERM
(stop parks — E3), and reports status from pid-liveness. The pid file
is bookkeeping; the ENGINE's own lock (F3) remains the only
single-instance authority — a port, a pid, or a panel must never be
the mutex (the OctoBot lesson).
"""
import os
import signal
import subprocess
import sys
from pathlib import Path


def _pid_path(fleet):
    p = Path(fleet)
    return p.parent.parent / 'logs' / f'engine-{p.stem}.pid'


def _log_path(fleet):
    p = Path(fleet)
    return p.parent.parent / 'logs' / f'engine-{p.stem}.log'


def status(fleet):
    """'running' (pid alive), 'stopped', or 'stale pid file' — a dead pid
    is reported as exactly that, never as a running engine."""
    pp = _pid_path(fleet)
    if not pp.exists():
        return 'stopped', None
    try:
        pid = int(pp.read_text().strip())
        os.kill(pid, 0)
        return 'running', pid
    except (ValueError, ProcessLookupError):
        return 'stale pid file', None
    except PermissionError:
        return 'running', None


def start(fleet):
    """Detached child: own session, output to its log file. Closing the
    panel does nothing to it. The engine's own lock refuses a double
    start in its own words — we spawn and let it speak."""
    st, pid = status(fleet)
    if st == 'running':
        return f'already running (pid {pid}) — the lock would refuse too'
    lp = _log_path(fleet)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, 'a') as log:
        proc = subprocess.Popen(
            [sys.executable, '-m', 'gridgremlin.main', str(fleet)],
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
    _pid_path(fleet).write_text(str(proc.pid))
    return f'started (pid {proc.pid}) — log: {lp}'


def stop(fleet):
    """SIGTERM, and stop still PARKS (E3): positions and their
    venue-resting orders survive a stopped engine."""
    st, pid = status(fleet)
    if st != 'running' or pid is None:
        return f'not running ({st})'
    os.kill(pid, signal.SIGTERM)
    _pid_path(fleet).unlink(missing_ok=True)
    return f'sent SIGTERM to pid {pid} — parked, not flattened (E3)'
