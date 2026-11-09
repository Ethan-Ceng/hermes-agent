"""CAS-checked proactive prune: one archived twin per changed live row."""

from sqlalchemy import insert, literal, select

from agent.message_metadata import DB_ROW_SNAPSHOT
from agent.transcript_repair import transcript_row_snapshot
from hermes_db.domains.sessions.postgres.support.compression_coverage import Coverage, exact_id
from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.operations import transcript_guards
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions
from hermes_db.tables.conversations import messages
from hermes_db.core.values import encode_config, model_config
from hermes_state_errors import PruneRowStaleError, PruneRowUnresolvedError
from hermes_db.domains.sessions.codec import _MESSAGE_WRITE_COLUMNS, _parse_tool_calls

_FIXED = {"session_id", "role", "tool_call_id", "timestamp", "active", "display_identity"}


def _call_ids(calls):
    return [call.get("id") if isinstance(call, dict) else None for call in (_parse_tool_calls(calls) or [])]


def _resolve(coverage, original):
    from agent.conversation_compression_archive import ABSORBED_ROW_IDS

    role = original.get("role")
    if role not in ("assistant", "tool") or original.get(ABSORBED_ROW_IDS):
        raise PruneRowUnresolvedError(f"a {role} message is not rewritten in place")
    row_id = exact_id(original)
    if row_id is not None:
        ids = [row_id]
    elif role == "tool" and original.get("tool_call_id"):
        ids = [row["id"] for row in coverage.rows if row["role"] == role and row["tool_call_id"] == original["tool_call_id"]]
    elif role == "assistant" and _call_ids(original.get("tool_calls")):
        wanted = _call_ids(original["tool_calls"])
        ids = [row["id"] for row in coverage.rows if row["role"] == role and _call_ids(row["tool_calls"]) == wanted]
    else:
        ids = coverage._matching_active_ids(None, None, original)
    if len(ids) != 1:
        raise PruneRowUnresolvedError(f"{len(ids)} live rows match a pruned {role} message")
    row = coverage.by_id.get(ids[0])
    if row is None or row["role"] != role:
        raise PruneRowStaleError(f"row {ids[0]} no longer holds the pruned {role} message")
    snapshot = original.get(DB_ROW_SNAPSHOT)
    differs = transcript_row_snapshot(row) != snapshot if isinstance(snapshot, str) else (
        coverage.identity(original) != coverage.identity(row, stored=True))
    if differs:
        raise PruneRowStaleError(f"row {ids[0]} no longer holds the pruned {role} message")
    return row


def _changes(row, original, replacement):
    role = row["role"]
    if replacement.get("role") != role:
        raise PruneRowUnresolvedError("a prune replacement changed the message role")
    before = codec._message_row_params(row["session_id"], role, original, _parse_tool_calls(original.get("tool_calls")),
        row["timestamp"], keep_reasoning=role == "assistant")
    after = codec._message_row_params(row["session_id"], role, replacement, _parse_tool_calls(replacement.get("tool_calls")),
        row["timestamp"], keep_reasoning=role == "assistant")
    return {column: value for column, old, value in zip(_MESSAGE_WRITE_COLUMNS, before, after)
            if old != value and column not in _FIXED}


def _archive_twin(conn, scope, session_id, row_id):
    columns = [column for column in messages.c if column.name != "id"]
    projection = [literal(0) if column.name == "active" else literal(1) if column.name == "compacted" else column for column in columns]
    conn.execute(insert(messages).from_select([column.name for column in columns], select(*projection).where(
        repo.where(scope, [session_id]), messages.c.id == row_id)))


def prune(conn, scope, session_id, changes, *, model_config_patch=None, turn_lease_holder=None, turn_lease_ttl_seconds=300):
    session = transcript_guards.check(conn, scope, session_id, turn_lease_holder=turn_lease_holder,
        turn_lease_ttl_seconds=turn_lease_ttl_seconds)
    coverage = Coverage(repo.select_rows(conn, scope, [session_id], messages.c.active == 1))
    updates = []
    for original, replacement in changes:
        row = _resolve(coverage, original)
        values = _changes(row, original, replacement)
        if values:
            updates.append((row["id"], values, replacement))
    for row_id, values, replacement in updates:
        _archive_twin(conn, scope, session_id, row_id)
        repo.update_row(conn, scope, session_id, row_id, values)
        replacement[DB_ROW_SNAPSHOT] = transcript_row_snapshot(repo.one(conn, scope, session_id, row_id))
    if model_config_patch is not None:
        config = model_config(session["model_config"])
        for key, value in model_config_patch.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        sessions.update_session(conn, scope, session_id, {"model_config": encode_config(config)})
    return len(updates)
