"""Current transcript imports in one scoped transaction; no database-file import."""

from copy import deepcopy
import time

from hermes_cli.timefmt import coerce_epoch
from hermes_db.operations import messages as writes, sessions as lifecycle
from hermes_db.integration.transfer.portability_values import values
from hermes_db.repositories import messages as transcript, sessions
from hermes_db.tables.conversations import messages, sessions as table
from hermes_db.core.values import encode_text, explicit_fork, model_config
from hermes_state_portability import _IMPORT_FLAG_COLS, _IMPORT_FLOAT_COLS, _IMPORT_INT_COLS, _IMPORT_MESSAGE_JSON_FIELDS, _IMPORT_PASSTHROUGH_COLS
from hermes_state_messages import _parse_tool_calls, _tool_calls_count
from utils import safe_json_loads


def import_row(conn, scope, raw, batch):
    sid = raw["id"]
    lifecycle.create_on_connection(conn, scope, sid, str(raw.get("source") or "import"),
        user_id=raw.get("user_id"), model=raw.get("model"), model_config=model_config(raw.get("model_config")),
        system_prompt=raw.get("system_prompt"), cwd=raw.get("cwd"), git_repo_root=raw.get("git_repo_root"))
    update = {column: raw.get(column) for column in _IMPORT_PASSTHROUGH_COLS}
    update.update({column: values._import_int_or_bounded(raw.get(column), column, 0) for column in _IMPORT_INT_COLS})
    update.update({column: values._import_float_or_finite(raw.get(column), column) for column in _IMPORT_FLOAT_COLS})
    update.update({column: int(bool(values._coerce_or(raw.get(column), int, 0))) for column in _IMPORT_FLAG_COLS})
    update["auto_archived"] &= update["archived"]
    started = coerce_epoch(raw.get("started_at"), session_id=sid, field="started_at")
    title = raw.get("title")
    update.update(started_at=time.time() if started is None else started, title=encode_text(title),
        title_search=title.replace("\x00", "") if title is not None else None)
    sessions.update_session(conn, scope, sid, update)
    batch = deepcopy(batch)
    for message in batch:
        for key in _IMPORT_MESSAGE_JSON_FIELDS:
            if isinstance(message.get(key), str):
                message[key] = safe_json_loads(message[key], default=message[key])
    writes.insert_rows(conn, scope, sid, batch, prune_checkpoints=False)
    live = []
    for message in batch:
        if values._coerce_or(message.get("active"), int, 1):
            live.append(message)
        else:
            conn.execute(messages.update().where(transcript.where(scope, [sid]), messages.c.id == message["_row_id"])
                .values(active=0, compacted=int(bool(values._coerce_or(message.get("compacted"), int, 0)))))
    writes.prune_old_checkpoints(conn, scope, sid, live)
    sessions.update_session(conn, scope, sid, {"message_count": len(live),
        "tool_call_count": sum(_tool_calls_count(_parse_tool_calls(message.get("tool_calls"))) for message in live)})
    transcript.reconcile_orders(conn, scope, sid)
    if batch:
        transcript.bump_revision(conn, scope, sid)


def attach_parents(conn, scope, updates):
    proposed, detached = dict(updates), 0
    for sid, parent_id in updates:
        if sessions.raw_session(conn, scope, parent_id) is None or _cycle(conn, scope, proposed, sid, parent_id):
            proposed.pop(sid, None)
            detached += 1
        else:
            sessions.update_session(conn, scope, sid, {"parent_session_id": parent_id})
    for sid in proposed:
        root, current = sid, sessions.raw_session(conn, scope, sid)
        while current["parent_session_id"] and not explicit_fork(current):
            parent = sessions.raw_session(conn, scope, current["parent_session_id"])
            if parent is None or parent["end_reason"] != "compression":
                break
            root, current = parent["lineage_root_id"], parent
        sessions.update_session(conn, scope, sid, {"lineage_root_id": root})
    return detached


def _cycle(conn, scope, proposed, sid, parent):
    seen, current = {sid}, parent
    while current:
        if current in seen:
            return True
        seen.add(current)
        if current in proposed:
            current = proposed[current]
        else:
            row = sessions.raw_session(conn, scope, current)
            current = row["parent_session_id"] if row else None
    return False


def import_current(conn, scope, normalized, *, canonical=False):
    from hermes_db.repositories.mutation_binding import bindings_agree, history_binding
    from hermes_state_runtime import RuntimeStoreError

    sessions.lock_store(conn, scope, exclusive=True)
    retired = [item["session"]["id"] for item in normalized if sessions.retired_session(conn, scope, item["session"]["id"])]
    if retired:
        if canonical:
            raise RuntimeStoreError("admission_conflict", field="sessions", detail=f"session {retired[0]} was deleted here; a deleted session is not restored")
        return {"ok": False, "imported": 0, "skipped": 0, "detached": 0,
            "errors": [f"session {sid} was deleted here; a deleted session is not restored" for sid in retired]}
    imported, skipped, parents = [], [], []
    for item in normalized:
        raw, batch = item["session"], item["messages"]
        sid = raw["id"]
        if sessions.raw_session(conn, scope, sid) is not None:
            skipped.append(sid)
            continue
        import_row(conn, scope, raw, batch)
        if parent := raw.get("parent_session_id"):
            parents.append((sid, parent))
        imported.append(sid)
    foreign = []
    if canonical:
        foreign = [(sid, parent) for sid, parent in parents if parent not in imported and (
            history_binding(conn, scope, parent) is None
            or not bindings_agree(history_binding(conn, scope, parent), history_binding(conn, scope, sid), scope))]
    detached = attach_parents(conn, scope, [pair for pair in parents if pair not in foreign]) + len(foreign)
    return {"ok": True, "imported": len(imported), "skipped": len(skipped), "imported_ids": imported,
        "skipped_ids": skipped, "detached": detached, "errors": []}
