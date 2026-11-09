"""Olm and Megolm records preserve SDK metadata and redacted-key tombstones."""

from sqlalchemy import delete, func, select, update
from hermes_db.domains.plugin_storage.matrix.postgres.queries import crypto as repo
from hermes_db.tables.matrix_crypto import olm_sessions, inbound, outbound


def has_session(conn, reference, *, sender_key):
    return conn.scalar(select(olm_sessions.c.session_id).where(repo.key(olm_sessions, reference, {"sender_key": sender_key})).limit(1)) is not None


def get_sessions(conn, reference, *, sender_key, latest=False):
    statement = select(olm_sessions).where(repo.key(olm_sessions, reference, {"sender_key": sender_key})).order_by(olm_sessions.c.decrypted_order.desc().nulls_last(), olm_sessions.c.session_id.desc())
    if latest:
        statement = statement.limit(1)
    return [repo.decode(row) for row in conn.execute(statement).mappings()]


def add_session(conn, reference, *, record):
    repo.upsert(conn, reference, olm_sessions, record)


def update_session(conn, reference, *, record):
    identity = {name: record[name] for name in ("sender_key", "session_id")}
    repo.change(conn, reference, olm_sessions, identity, {name: value for name, value in record.items() if name != "created_at"})


def put_group_session(conn, reference, *, record):
    repo.upsert(conn, reference, inbound, dict(record, withheld_code=None, withheld_reason=None))


def get_group_session(conn, reference, *, room_id, session_id):
    return repo.row(conn, reference, inbound, dict(room_id=room_id, session_id=session_id))


def has_group_session(conn, reference, *, room_id, session_id):
    row = get_group_session(conn, reference, room_id=room_id, session_id=session_id)
    return row is not None and row["pickle"] is not None


def _redact(conn, reference, condition, reason):
    statement = update(inbound).where(repo.scope(inbound, reference), inbound.c.pickle.is_not(None), condition).values(
        pickle=None, forwarding_json=None, withheld_code="com.beeper.redacted", withheld_reason=repo.values(inbound, {"withheld_reason": f"Session redacted: {reason}"})["withheld_reason"])
    return list(conn.scalars(statement.returning(inbound.c.session_id)))


def redact_group_session(conn, reference, *, room_id, session_id, reason):
    _redact(conn, reference, repo.key(inbound, reference, dict(room_id=room_id, session_id=session_id)), reason)


def redact_group_sessions(conn, reference, *, room_id, sender_key, reason):
    if not room_id and not sender_key:
        raise ValueError("Either room_id or sender_key must be provided")
    fields = {name: value for name, value in dict(room_id=room_id, sender_key=sender_key).items() if value}
    condition = repo.key(inbound, reference, fields) & (inbound.c.is_scheduled == 0) & inbound.c.received_order.is_not(None)
    return _redact(conn, reference, condition, reason)


def redact_expired_group_sessions(conn, reference):
    stamp = float(conn.scalar(select(func.extract("epoch", func.clock_timestamp()))))
    condition = (inbound.c.is_scheduled == 0) & inbound.c.received_order.is_not(None) & inbound.c.max_age_ms.is_not(None) & (
        inbound.c.received_order + 2 * inbound.c.max_age_ms / 1000 < stamp)
    return _redact(conn, reference, condition, "expired")


def redact_outdated_group_sessions(conn, reference):
    return _redact(conn, reference, inbound.c.received_order.is_(None), "outdated")


def add_outbound_group_session(conn, reference, *, record):
    repo.upsert(conn, reference, outbound, record)


def update_outbound_group_session(conn, reference, *, record):
    repo.change(conn, reference, outbound, {name: record[name] for name in ("room_id", "session_id")},
        {name: record[name] for name in ("pickle", "message_count", "last_used")})


def get_outbound_group_session(conn, reference, *, room_id):
    return repo.row(conn, reference, outbound, {"room_id": room_id})


def remove_outbound_group_sessions(conn, reference, *, rooms):
    from hermes_db.core.values import encode_text
    conn.execute(delete(outbound).where(repo.scope(outbound, reference), outbound.c.room_id.in_([encode_text(room) for room in rooms])))
