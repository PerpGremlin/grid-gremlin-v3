# The event vocabulary. Order mechanics are logged, not shipped, unless asked.
EVENT_KINDS = ('fleet', 'start', 'seed', 'skip', 'placed', 'cancel', 'amend', 'fill',
               'exit', 'tp', 'repeat', 'funding', 'margin', 'backoff', 'warn', 'kill',
               'net', 'dryrun')
ORDER_KINDS = ('placed', 'cancel', 'amend', 'skip')
LOG_ONLY_KINDS = ('net',)    # network weather: the terminal's business, never the phone's


class Notifier:
    def __init__(self, ship_orders=False, sink=None):
        self.ship_orders = ship_orders
        self.sink = sink or (lambda line: print(line, flush=True))

    def event(self, kind, botid, text, icon=''):
        # the terminal stays clean ASCII — it is the audit trail tools grep;
        # the icon is the PHONE's affordance only (TelegramNotifier)
        route = 'log' if ((kind in ORDER_KINDS and not self.ship_orders)
                          or kind in LOG_ONLY_KINDS) else 'ship'
        label = kind if botid == kind else f'{kind} {botid}'   # no "fleet fleet"
        self.sink(f'[{route}] {label}: {text}')


class TelegramNotifier(Notifier):
    """Shipped events go to Telegram, coalesced, never faster than
    MIN_INTERVAL; order mechanics stay in the log. Everything still prints —
    the terminal is the audit trail, the phone is the alert channel."""

    MIN_INTERVAL = 3.0

    def __init__(self, token, chat_id, ship_orders=False, transport=None,
                 clock=None, sink=None):
        super().__init__(ship_orders=ship_orders, sink=sink)
        self.token = token
        self.chat_id = chat_id
        self._transport = transport or self._http
        self._clock = clock or __import__('time').time
        self._buffer = []
        self._last_send = 0.0

    def _http(self, text):
        import json
        import urllib.request
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/sendMessage',
            data=json.dumps({'chat_id': self.chat_id, 'text': text}).encode(),
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10).read()

    def event(self, kind, botid, text, icon=''):
        super().event(kind, botid, text)
        if (kind in ORDER_KINDS and not self.ship_orders) \
                or kind in LOG_ONLY_KINDS:
            return
        prefix = f'{icon} ' if icon else ''
        label = kind if botid == kind else f'{kind} {botid}'   # phone too:
        self._buffer.append(f'{prefix}{label}: {text}')        # no "fleet fleet"
        # a kill page must not sit in the buffer until some later event
        # arrives (the audit's M6) — it flushes NOW, rate limit or not
        self._maybe_flush(force=(kind == 'kill'))

    def _maybe_flush(self, force=False):
        if not self._buffer:
            return
        now = self._clock()
        if not force and now - self._last_send < self.MIN_INTERVAL:
            return
        try:
            self._transport('\n'.join(self._buffer))
            self._buffer = []
            self._last_send = now
        except OSError:
            pass                    # keep buffering; the terminal already has it

    def close(self):
        self._maybe_flush(force=True)


class VenueNotifier:
    """The seam that colours a bot's phone events at a glance (owner ask,
    2026-08-05) — wraps once at construction, zero call-site changes. Takes
    the ICON, not the venue name: this module stays venue-blind (A6)."""

    def __init__(self, inner, icon):
        self._inner = inner
        self._icon = icon

    def event(self, kind, botid, text):
        self._inner.event(kind, botid, text, icon=self._icon)
