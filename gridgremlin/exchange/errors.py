# The venue-neutral error contract (E6). Kinds the engine reacts to; codes stay
# in the venue packages. Per-venue emit-ability is documented at each client.
KINDS = ('gone', 'not_modified', 'cannot_modify', 'ro_capacity', 'margin',
         'rate_limit', 'post_only_reject', 'partial_read', 'other')


class VenueError(Exception):
    """kind: one of KINDS. ambiguous: the write MAY have landed (E6)."""

    def __init__(self, msg, kind='other', ambiguous=False):
        super().__init__(msg)
        self.kind = kind
        self.ambiguous = ambiguous
