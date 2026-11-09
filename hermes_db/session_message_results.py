"""Durable between-turn result notes and bounded Todo restoration."""

import json

from sqlalchemy import func, select

from hermes_db.message_codec import codec
from hermes_db.operations import messages as operations, transcript_guards
from hermes_db.repositories import messages as repo, sessions as session_repo
from hermes_db.backends.postgresql.expressions.projections import display_value, query_token
from hermes_db.tables.conversations import messages
from hermes_state_identity import _uid_list


class SessionMessageResults:
    def append_delegation_delivery(self, session_id, content, metadata):
        if not metadata.get("delegation_id"):
            raise ValueError("Delegation delivery requires a stable delegation_id")
        kind = "hidden" if metadata.get("presentation_suppressed") else "async_delegation_complete"
        return self._append_result(session_id, content, kind, metadata,
                                   {"delegation_id": metadata["delegation_id"], "delivery_notice": metadata.get("delivery_notice", "")})

    def append_completion_note(self, session_id, admission_id, content, display_kind, metadata):
        return self._append_result(session_id, content, display_kind, {**metadata, "completion_admission": admission_id},
                                   {"completion_admission": admission_id})

    def _append_result(self, session_id, content, display_kind, metadata, identity):
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            ids = repo.resume_lineage(conn, self.scope, session_id)
            conditions = [repo.where(self.scope, ids)]
            for key, value in identity.items():
                column = display_value(messages.c.display_metadata, key)
                if key == "delivery_notice":
                    column = func.coalesce(column, query_token(''))
                conditions.append(column == query_token(value))
            if "delegation_id" in identity:
                conditions.append(messages.c.display_kind.in_(("async_delegation_complete", "hidden")))
            row_id = conn.scalar(select(messages.c.id).where(*conditions).limit(1))
            if row_id is not None:
                return row_id
            transcript_guards.check(conn, self.scope, session_id, reject_active_turn_lease=True)
            batch = [{"role": "user", "content": content, "display_kind": display_kind, "display_metadata": metadata}]
            operations.insert_rows(conn, self.scope, session_id, batch)
            repo.bump_counters(conn, self.scope, session_id, 1, 0)
            return batch[0]["_row_id"]

    def get_latest_todo_result(self, session_id, *, max_chars=None):
        if not session_id:
            return None
        if max_chars is None:
            from tools.todo_tool import MAX_TODO_RESULT_CHARS
            max_chars = MAX_TODO_RESULT_CHARS
        with self._read() as conn:
            ids = repo.resume_lineage(conn, self.scope, session_id)
            removed = _removed_todos(conn, self.scope, ids)
            for sid in reversed(ids):
                before_id = 2**63 - 1
                while True:
                    rows = repo.select_rows(conn, self.scope, [sid], messages.c.role == "tool", repo.visible(),
                        messages.c.tool_name.in_(("todo_list", "todo")), messages.c.id < before_id,
                        func.length(messages.c.content) <= max_chars * 4 + 1, limit=100, latest=True)
                    if not rows:
                        break
                    for row in reversed(rows):
                        if not row["tool_call_id"] or any(removed.get(key, 0) > row["id"] for key in _copy_keys(row)):
                            continue
                        prior = repo.select_rows(conn, self.scope, [sid], messages.c.id < row["id"], repo.visible(),
                            messages.c.role.in_(("assistant", "user", "system")), limit=1, latest=True)
                        if prior and _valid_todo(row, prior[0], max_chars):
                            return row["content"]
                    before_id = rows[0]["id"]
        return None


def _valid_todo(row, prior, max_chars):
    if prior["role"] != "assistant" or not row["content"] or len(row["content"]) > max_chars:
        return False
    try:
        calls = json.loads(prior["tool_calls"]) if prior["tool_calls"] else []
        if not isinstance(calls, list) or not any(_todo_call(call, row["tool_call_id"]) for call in calls):
            return False
        data = json.loads(row["content"])
        if not isinstance(data, dict) or not isinstance(data.get("todos"), list):
            return False
        int(data.get("revision") or 0)
        return True
    except (ValueError, TypeError):
        return False


def _todo_call(call, call_id):
    if not isinstance(call, dict) or call.get("id") != call_id:
        return False
    function = call.get("function")
    if not isinstance(function, dict):
        return False
    if function.get("name") in ("todo_list", "todo"):
        return True
    if function.get("name") != "tool_call":
        return False
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    calls = arguments.get("calls") if isinstance(arguments, dict) else None
    return isinstance(calls, list) and any(isinstance(inner, dict) and inner.get("name") in ("todo_list", "todo") for inner in calls)


def _copy_keys(row):
    return [row["display_identity"], *(("uid", uid) for uid in (row["message_uid"], *_uid_list(row["absorbed_message_uids"])) if uid)]


def _removed_todos(conn, scope, ids):
    columns = (messages.c.id, messages.c.display_identity, messages.c.message_uid, messages.c.absorbed_message_uids)
    rows = conn.execute(select(*columns).where(repo.where(scope, ids), messages.c.active == 0, messages.c.compacted == 0,
        messages.c.role == "tool", messages.c.tool_name.in_(("todo_list", "todo")))).mappings()
    removed = {}
    for row in rows:
        for key in _copy_keys(row):
            removed[key] = max(removed.get(key, 0), row["id"])
    return removed
