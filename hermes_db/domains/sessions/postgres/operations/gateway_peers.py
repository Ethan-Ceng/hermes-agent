"""Peer identity settlement and orphan adoption under the map/root fences."""

import time

from hermes_db.domains.sessions.postgres.operations import sessions as lifecycle
from hermes_db.domains.sessions.postgres.queries import messages, sessions
from hermes_db.core.values import encode_text


def record(conn, scope, session_id, *, source, messaging_platform, own_profile=None, include_compression_ancestors=False, **peer):
    sessions.lock_store(conn, scope, exclusive=True)
    if sessions.raw_session(conn, scope, session_id) is None:
        if include_compression_ancestors:
            return
        lifecycle.create_on_connection(conn, scope, session_id, source, own_profile=own_profile, **peer)
    ids = messages.resume_lineage(conn, scope, session_id) if include_compression_ancestors else [session_id]
    rows = [sessions.raw_session(conn, scope, sid) for sid in ids]
    for root in sorted({row["lineage_root_id"] for row in rows}):
        sessions.lock_root(conn, scope, root)
    for row in rows:
        values = {"source": source, **{key: peer.get(key) for key in ("session_key", "user_id", "chat_id", "chat_type", "thread_id")}}
        for name in ("display_name", "origin_json", "transport_profile"):
            if peer.get(name) is not None:
                values[name] = encode_text(peer[name]) if name == "display_name" else peer[name]
        sessions.update_session(conn, scope, row["id"], values)
    if include_compression_ancestors:
        from hermes_db.domains.sessions.postgres.operations.gateway_local_handoff import hand_off_moved
        hand_off_moved(conn, scope, set(ids), messaging_platform=messaging_platform)


def adopt(conn, scope, orphan_id, donor_id, *, owner):
    if not orphan_id or not donor_id or orphan_id == donor_id:
        return False
    sessions.lock_store(conn, scope, exclusive=True)
    donor, orphan = (sessions.raw_session(conn, scope, sid) for sid in (donor_id, orphan_id))
    if donor is None or orphan is None or not donor["session_key"] or orphan["session_key"]:
        return False
    if (donor["source"] or "") != (orphan["source"] or ""):
        return False
    if owner is not None and (donor["profile_name"] or owner) != (orphan["profile_name"] or owner):
        return False
    for root in sorted({donor["lineage_root_id"], orphan["lineage_root_id"]}):
        sessions.lock_root(conn, scope, root)
    fields = ("chat_id", "chat_type", "thread_id", "user_id", "origin_json", "display_name")
    values = {name: donor[name] for name in fields if orphan[name] is None}
    values.update(session_key=donor["session_key"], parent_session_id=orphan["parent_session_id"] or donor_id)
    sessions.update_session(conn, scope, orphan_id, values)
    sessions.update_session(conn, scope, donor_id, {"ended_at": donor["ended_at"] or time.time(), "end_reason": "superseded_by_repair"})
    return True
