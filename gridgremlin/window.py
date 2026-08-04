# The placement window (SPEC W1-W3).


def window(desired, split_ref, place_within_pct):
    """W1: only rungs within the band go live; cancellation never uses this."""
    lo = split_ref * (1.0 - place_within_pct)
    hi = split_ref * (1.0 + place_within_pct)
    return [o for o in desired if lo <= o['price'] <= hi]
