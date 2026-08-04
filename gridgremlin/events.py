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
