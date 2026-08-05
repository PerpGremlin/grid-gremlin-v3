# Tombstones (SPEC X7): the ONE narrow local durable fact E3 permits.
# The exchange cannot express "this bot's stop fired" — a flat position is
# indistinguishable from a fresh start — so D1's prevents-restart clause
# needs a file. Persisted BEFORE the flatten (a crash mid-stop still refuses
# revival); removal is a deliberate operator act, never automatic.
import json
import time
from pathlib import Path


class TombstoneError(Exception):
    pass


class Tombstones:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self._rows = json.loads(self.path.read_text())
        except FileNotFoundError:
            self._rows = {}
        except (OSError, ValueError) as e:
            # fail CLOSED: a corrupt/unreadable tombstone file must never
            # silently revive stop-fired bots (the audit's M3)
            raise TombstoneError(
                f'{path}: unreadable ({e}) — fix or delete it, deliberately; '
                'refusing to build rather than revive stopped bots') from e

    def has(self, botid):
        return botid in self._rows

    def reason(self, botid):
        return (self._rows.get(botid) or {}).get('reason', '')

    def add(self, botid, reason):
        """Durable before returning — the caller flattens only after this."""
        self._rows[botid] = {'reason': reason, 't': int(time.time())}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self._rows, indent=1))
        tmp.replace(self.path)
