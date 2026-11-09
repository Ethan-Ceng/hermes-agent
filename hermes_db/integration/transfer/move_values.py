"""Current PG move fingerprints and opaque resource binding, never connection secrets."""

import json
from hermes_db.core.values import digest

PREPARED = "hermes:profile-move:prepared:"
IMPORTED = "hermes:profile-move:imported:"






def snapshot_digest(snapshot):
    # Parent-first source retirement detaches remaining children. Those map
    # changes must not masquerade as newly generated content in the next move.
    ignored = {"store_id", "parent_session_id", "lineage_root_id", "runtime_revision", "runtime_generation",
        "delegate_origin", "has_delegate_marker", "has_branch_marker"}
    data = {name: snapshot[name] for name in ("session", "system_prompt", "tool_pin", "messages", "usage")}
    return digest({**data, "session": {name: value for name, value in snapshot["session"].items() if name not in ignored}})


def recipient_snapshot_digest(snapshot, message_count):
    # Normal appends may extend a verified copy. Rewrites, prompt changes, or
    # other metadata/usage changes require retaining the donor for reconciliation.
    growth = {"last_active", "message_count", "tool_call_count", "transcript_revision"}
    return snapshot_digest({**snapshot, "messages": snapshot["messages"][:message_count],
        "session": {key: value for key, value in snapshot["session"].items() if key not in growth}})


def prepared_key(sid):
    return PREPARED + digest(sid)


def imported_key(source_store, sid):
    return IMPORTED + digest([source_store, sid])
