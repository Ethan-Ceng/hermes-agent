"""Core row-addressed transcript repair under the caller's lineage lock."""

from agent.context_compressor import _DB_PERSISTED_MARKER
from agent.message_metadata import CANONICAL_ROW, DB_ROW_SNAPSHOT, RESTORED_FROM_STORE, message_uid_or_none
from agent.transcript_repair import (
    _LIVE_MISSING_METADATA, _OWNED_COLUMNS, _REPAIR_COLUMNS, _same_as_stored, is_content_blank, transcript_row_snapshot,
)
from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo
from hermes_db.tables.conversations import messages
from hermes_state_identity import _fill_missing_tool_call_uids, _restore_row_identity


def resolve_row(conn, scope, session_id, row_id, role):
    row = repo.one(conn, scope, session_id, row_id)
    if row is None or row["role"] != role:
        return None
    if row["active"] or row["display_identity"] is None:
        return row
    from hermes_db.domains.sessions.postgres.support.message_codec import stored_values
    stored = stored_values(row)
    conditions = [messages.c.active == 1, messages.c.role == role, messages.c.id != row_id,
                  messages.c.display_identity == row["display_identity"], messages.c.timestamp == row["timestamp"]]
    conditions.extend(messages.c[column].is_not_distinct_from(stored[column]) for column in _REPAIR_COLUMNS)
    clones = repo.select_rows(conn, scope, [session_id], *conditions, limit=2, latest=True)
    return clones[0] if len(clones) == 1 else row


def resolve_batch(conn, scope, session_id, batch):
    from agent.session_persistence import _PERSIST_AFTER_ADMISSION_INTERRUPT

    uids = {message_uid_or_none(msg) for msg in batch if msg.get(RESTORED_FROM_STORE) is True
            and not isinstance(msg.get("_row_id"), int) and not isinstance(msg.get(DB_ROW_SNAPSHOT), str)} - {None}
    durable = {}
    if uids:
        for row in repo.select_rows(conn, scope, [session_id], messages.c.active == 1, messages.c.message_uid.in_(uids)):
            durable.setdefault(row["message_uid"], []).append(row)
    inserted = []
    for msg in batch:
        row = _find_target(conn, scope, session_id, msg)
        if row is None:
            if durable.get(message_uid_or_none(msg)) and not msg.get(_PERSIST_AFTER_ADMISSION_INTERRUPT) and _same_as_stored(
                    msg, durable[message_uid_or_none(msg)],
                    lambda item, timestamp: codec._serialized_message_row(session_id, item, timestamp),
                    codec._encode_content, codec._decode_content):
                msg[_DB_PERSISTED_MARKER] = True
            else:
                inserted.append(msg)
            continue
        _repair_target(conn, scope, session_id, row, msg)
    return inserted


def _find_target(conn, scope, session_id, msg):
    role = msg.get("role", "unknown")
    if isinstance(msg.get("_row_id"), int):
        return resolve_row(conn, scope, session_id, msg["_row_id"], role)
    if isinstance(msg.get(DB_ROW_SNAPSHOT), str) and message_uid_or_none(msg):
        rows = repo.select_rows(conn, scope, [session_id], messages.c.active == 1, messages.c.role == role,
            messages.c.message_uid == message_uid_or_none(msg), limit=1, latest=True)
        return rows[0] if rows else None
    return None


def _repair_target(conn, scope, session_id, row, msg):
    msg["_row_id"] = row["id"]
    _fill_missing_tool_call_uids(row, msg)
    expected, canonical = msg.get(DB_ROW_SNAPSHOT), None
    if isinstance(expected, str):
        if transcript_row_snapshot(row) != expected:
            canonical = codec._decoded_repair_row(row)
        else:
            serialized = codec._serialized_message_row(session_id, msg, row["timestamp"])
            if serialized["token_count"] is None:
                serialized["token_count"] = row["token_count"]
            changes = {column: serialized[column] for column in _OWNED_COLUMNS if row[column] != serialized[column]}
            if changes:
                repo.update_row(conn, scope, session_id, row["id"], changes)
            missing = {key: row[key] for key in _LIVE_MISSING_METADATA if msg.get(key) is None}
            if any(value is not None for value in missing.values()):
                decoded = codec._decoded_repair_row(row)
                canonical = {**{key: decoded[key] for key in missing if key in decoded}, "_metadata_only": True}
    elif msg.get("role") == "assistant":
        if is_content_blank(codec._decode_content(row["content"])):
            repo.update_row(conn, scope, session_id, row["id"], {"content": codec._encode_content(msg.get("content"))})
        else:
            canonical = {"content": codec._decode_content(row["content"]), "_content_only": True}
    final = repo.one(conn, scope, session_id, row["id"])
    msg["timestamp"] = final["timestamp"]
    _restore_row_identity(final, msg)
    msg[DB_ROW_SNAPSHOT] = transcript_row_snapshot(final)
    if canonical:
        msg[CANONICAL_ROW] = canonical
    else:
        msg.pop(CANONICAL_ROW, None)
