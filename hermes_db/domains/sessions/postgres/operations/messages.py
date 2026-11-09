"""Atomic message append/replace; caller stamps become visible only after commit."""

from copy import deepcopy
import time

from sqlalchemy import func

from agent.context_compressor import _is_checkpoint_item, _newest_checkpoint_carrier
from agent.message_metadata import CANONICAL_ROW, DB_ROW_SNAPSHOT, MESSAGE_UID, stamp_message_uid
from agent.transcript_repair import transcript_row_snapshot
from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.operations import transcript_guards, transcript_repair
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo
from hermes_db.tables.conversations import messages, sessions
from hermes_state_messages import _coerce_timestamp, _tool_calls_count, _tool_calls_len
from hermes_db.domains.sessions.codec import _parse_tool_calls


def insert_rows(conn, scope, session_id, batch, *, keep_all_reasoning=False, prune_checkpoints=True):
    now, total, tool_index = time.time(), 0, {}
    for msg in batch:
        calls = _parse_tool_calls(msg.get("tool_calls"))
        timestamp = _coerce_timestamp(msg.get("timestamp"), now)
        stamp_message_uid(msg)
        codec._stamp_tool_call_uids(msg, calls, tool_index)
        role = msg.get("role", "unknown")
        row = dict(zip(_write_columns(), codec._message_row_params(session_id, role, msg, calls, timestamp,
                                                                 keep_reasoning=keep_all_reasoning or role == "assistant")))
        msg["_row_id"] = repo.insert_row(conn, scope, row)
        msg["timestamp"] = timestamp
        total += _tool_calls_count(calls)
        now = max(now, timestamp) + 1e-6
    repo.reconcile_orders(conn, scope, session_id)
    if prune_checkpoints:
        prune_old_checkpoints(conn, scope, session_id, batch)
    for msg in batch:
        msg[DB_ROW_SNAPSHOT] = transcript_row_snapshot(repo.one(conn, scope, session_id, msg["_row_id"]))
    return len(batch), total


def _write_columns():
    from hermes_db.domains.sessions.codec import _MESSAGE_WRITE_COLUMNS
    return _MESSAGE_WRITE_COLUMNS


def prune_old_checkpoints(conn, scope, session_id, batch):
    import json

    carrier = _newest_checkpoint_carrier(batch, "codex_reasoning_items")
    if carrier < 0:
        return
    for row in repo.select_rows(conn, scope, [session_id], messages.c.active == 1, messages.c.role == "assistant",
            messages.c.id < batch[carrier]["_row_id"], messages.c.codex_reasoning_items.is_not(None)):
        try:
            items = json.loads(row["codex_reasoning_items"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(items, list) and any(_is_checkpoint_item(item) for item in items):
            kept = [item for item in items if not _is_checkpoint_item(item)]
            repo.update_row(conn, scope, session_id, row["id"], {"codex_reasoning_items": codec._reasoning_json_text(kept)})


def append(transactions, scope, session_id, batch, *, single=False, **guards):
    _stamp_logical_identities(batch)
    work = deepcopy(batch)
    with transactions.write() as conn:
        inserted = append_on_connection(conn, scope, session_id, work, single=single, **guards)
    _publish_stamps(batch, work)
    return work[0]["_row_id"] if single else inserted


def append_on_connection(conn, scope, session_id, batch, *, single=False, **guards):
    transcript_guards.check(conn, scope, session_id, **guards)
    fresh = batch if single else transcript_repair.resolve_batch(conn, scope, session_id, batch)
    inserted, tools = insert_rows(conn, scope, session_id, fresh, keep_all_reasoning=single)
    repo.bump_counters(conn, scope, session_id, inserted, tools)
    return inserted


def _publish_stamps(batch, work):
    keys = ("_row_id", "timestamp", DB_ROW_SNAPSHOT, CANONICAL_ROW, MESSAGE_UID, "_tool_call_uids", "_tool_call_uid",
            "_db_persisted")
    for original, result in zip(batch, work):
        for key in keys:
            if key in result:
                original[key] = result[key]
            elif key == CANONICAL_ROW:
                original.pop(key, None)


def _stamp_logical_identities(batch):
    index = {}
    for msg in batch:
        stamp_message_uid(msg)
        codec._stamp_tool_call_uids(msg, _parse_tool_calls(msg.get("tool_calls")), index)


def replace(transactions, scope, session_id, batch, **options):
    _stamp_logical_identities(batch)
    work = deepcopy(batch)
    with transactions.write() as conn:
        replace_on_connection(conn, scope, session_id, work, **options)
    _publish_stamps(batch, work)


def replace_on_connection(conn, scope, session_id, batch, *, active_only=False, archive_dropped=False,
                          reject_active_turn_lease=False, expected_active_ids=None):
    transcript_guards.check(conn, scope, session_id, reject_active_turn_lease=reject_active_turn_lease,
                            reject_active_compression_lock=reject_active_turn_lease)
    ids = repo.active_ids(conn, scope, session_id)
    if expected_active_ids is not None and ids != expected_active_ids:
        raise RuntimeError("active transcript changed before the rewrite could be persisted")
    kept, kept_tools = 0, 0
    if archive_dropped:
        live = repo.select_rows(conn, scope, [session_id], messages.c.active == 1, limit=len(batch) + 1)
        kept = _kept_prefix(live, batch)
        kept_tools = sum(_tool_calls_len(row["tool_calls"], scalar=1) for row in live[:kept])
        if kept < len(live):
            conn.execute(messages.update().where(repo.where(scope, [session_id]), messages.c.active == 1,
                messages.c.id >= live[kept]["id"]).values(active=0))
    else:
        condition = [messages.c.active == 1] if active_only else []
        conn.execute(messages.delete().where(repo.where(scope, [session_id]), *condition))
    inserted, tools = insert_rows(conn, scope, session_id, batch[kept:])
    session_repo.update_session(conn, scope, session_id, {"message_count": kept + inserted, "tool_call_count": kept_tools + tools})
    repo.bump_revision(conn, scope, session_id)


def _kept_prefix(live, batch):
    kept = 0
    for row, msg in zip(live, batch):
        identity = codec._row_identity(msg.get("role", "unknown"), msg.get("content"), msg.get("tool_call_id"),
                                       _parse_tool_calls(msg.get("tool_calls")))
        stored = codec._row_identity(row["role"], codec._decode_content(row["content"]), row["tool_call_id"],
                                     _parse_tool_calls(row["tool_calls"]))
        if identity != stored:
            break
        msg["_row_id"] = row["id"]
        msg[MESSAGE_UID] = row["message_uid"]
        kept += 1
    return kept


def rewind(conn, scope, session_id, target_id, *, preserve_compaction_handoff=False,
           expected_active_ids=None, expected_target_content=None):
    transcript_guards.check(conn, scope, session_id, reject_active_turn_lease=True, reject_active_compression_lock=True)
    ids = repo.active_ids(conn, scope, session_id)
    if expected_active_ids is not None and ids != expected_active_ids:
        raise RuntimeError("active transcript changed before the rewind could be persisted")
    row = repo.one(conn, scope, session_id, target_id)
    if row is None or row["role"] != "user":
        raise ValueError("rewind target must be a user message in this session")
    replacement = None
    if preserve_compaction_handoff or expected_target_content is not None:
        replacement = codec._split_rewind_target(row, expected_target_content, preserve_compaction_handoff)
    removed = [row_id for row_id in ids if row_id >= target_id]
    conn.execute(messages.update().where(repo.where(scope, [session_id]), messages.c.id.in_(removed)).values(active=0))
    if replacement is not None:
        insert_rows(conn, scope, session_id, [replacement])
    live = repo.select_rows(conn, scope, [session_id], messages.c.active == 1)
    session_repo.update_session(conn, scope, session_id, {"message_count": len(live),
        "tool_call_count": sum(_tool_calls_len(item["tool_calls"], scalar=1) for item in live),
        "rewind_count": func.coalesce(sessions.c.rewind_count, 0) + 1})
    repo.reconcile_orders(conn, scope, session_id)
    repo.bump_revision(conn, scope, session_id)
    return {"rewound_count": len(removed), "target_message": {**row, "content": codec._decode_content(row["content"])},
            "new_head_id": live[-1]["id"] if live else None,
            **({"replacement_message_id": replacement["_row_id"], "replacement_message_uid": replacement[MESSAGE_UID]}
               if replacement is not None else {})}
