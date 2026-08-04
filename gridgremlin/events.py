# The event vocabulary. Order mechanics are logged, not shipped, unless asked.
EVENT_KINDS = ('fleet', 'start', 'seed', 'skip', 'placed', 'cancel', 'amend', 'fill',
               'exit', 'tp', 'repeat', 'funding', 'margin', 'backoff', 'warn', 'kill', 'dryrun')
ORDER_KINDS = ('placed', 'cancel', 'amend')


class Notifier:
    def __init__(self, ship_orders=False, sink=None):
        self.ship_orders = ship_orders
        self.sink = sink or (lambda line: print(line, flush=True))

    def event(self, kind, botid, text):
        route = 'log' if kind in ORDER_KINDS and not self.ship_orders else 'ship'
        self.sink(f'[{route}] {kind} {botid}: {text}')


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

    def event(self, kind, botid, text):
        super().event(kind, botid, text)
        if kind in ORDER_KINDS and not self.ship_orders:
            return
        self._buffer.append(f'{kind} {botid}: {text}')
        self._maybe_flush()

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
