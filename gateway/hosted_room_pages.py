"""Byte-bounded replay serialization shared by the native and Core stores."""

import json


def replay_page(events, *, since_seq, latest_seq, authority, max_bytes, error):
    def build(items):
        cursor = items[-1]["seq"] if items else since_seq
        return {"events": items, "cursor": cursor, "latest_seq": latest_seq, "has_more": cursor < latest_seq, "authority": authority}
    def fits(items):
        return len(json.dumps(build(items), ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= max_bytes
    if events and not fits(events):
        low, high = 1, len(events)
        while low < high:
            middle = (low + high + 1) // 2
            low, high = (middle, high) if fits(events[:middle]) else (low, middle - 1)
        events = events[:low]
        if not fits(events):
            raise error("hosted room event exceeds replay page limit")
    return build(events)
