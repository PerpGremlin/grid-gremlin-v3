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


# E6/E7: the reaction map — data, not scattered ifs. No kind kills (E7);
# a stop rule or the operator are the only paths to stand-down.
KIND_REACTIONS = {
    'gone': 'treat_done',
    'not_modified': 'treat_done',
    'cannot_modify': 'refuse_row_at_build',
    'ro_capacity': 'retry_next_cycle',
    'margin': 'backoff_growth_only',
    'rate_limit': 'wait_for_window',
    'post_only_reject': 'leave_to_flap_guard',
    'partial_read': 'retry_next_cycle',
    'other': 'warn_and_retry',
}
