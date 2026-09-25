# The slide state (SPEC G22): the SECOND narrow local durable fact E3
# permits, beside tombstones. The exchange cannot express "this bot's window
# is k rungs from home" — resting orders reveal it only while they rest.
# Persisted BEFORE the orders move (a crash mid-slide resumes at the new
# window, whose orders may already rest); missing means home, which is safe
# (orders outside home are cancelled and re-planned: a lost ratchet, never
# lost money); unreadable fails CLOSED like a tombstone file.
import json
from pathlib import Path


class SlideStateError(Exception):
    pass


class SlideState:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self._rows = json.loads(self.path.read_text())
        except FileNotFoundError:
            self._rows = {}
        except (OSError, ValueError) as e:
            raise SlideStateError(
                f'{path}: unreadable ({e}) — fix or delete it, deliberately; '
                'refusing to build rather than guess every window') from e
        if not isinstance(self._rows, dict) or any(
                not isinstance(v, int) or isinstance(v, bool)
                for v in self._rows.values()):
            raise SlideStateError(f'{path}: malformed — offsets must be integers')

    def get(self, botid):
        return int(self._rows.get(botid, 0))

    def set(self, botid, offset):
        """Durable before returning — the caller moves orders only after this."""
        self._rows[botid] = int(offset)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self._rows, indent=1))
        tmp.replace(self.path)
