"""Core statements always carry both store and immutable Board identity."""

import json
import time
from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.kanban import tasks, links, comments, events, kanban_boards as boards, TASK_TEXT_FIELDS
from hermes_db.core.values import decode_text, encode_text


def scope(table, store):
    return and_(table.c.store_id == store.scope.require_store_id(), table.c.board_id == store.board_id)


def key(store, task_id, table=tasks):
    column = table.c.id if table is tasks else table.c.task_id
    return and_(scope(table, store), column == encode_text(task_id))


def owner(store):
    return {"store_id": store.scope.require_store_id(), "board_id": store.board_id}


def lock_board(conn, store):
    row = conn.execute(select(boards.c.archived).where(scope(boards, store)).with_for_update()).one_or_none()
    if row is None or row.archived:
        raise ValueError("Kanban Board was removed or archived; acquire the active Board again")


def encode_task(values):
    return {name: encode_text(value) if name in TASK_TEXT_FIELDS else value for name, value in values.items()}


def decode_task(row):
    return {name: decode_text(value) if name in TASK_TEXT_FIELDS else value for name, value in row.items()}


def decode_record(row):
    return {name: decode_text(value) if isinstance(value, (bytes, memoryview)) else value for name, value in row.items()}


def get(conn, store, task_id):
    row = conn.execute(select(tasks).where(key(store, task_id))).mappings().one_or_none()
    return decode_task(row) if row is not None else None


def require_task(conn, store, task_id):
    row = get(conn, store, task_id)
    if row is None:
        raise ValueError(f"unknown task {task_id}")
    return row


def task_update(conn, store, task_id, **values):
    if "status" in values and values["status"] not in {"done", "archived", "failed", "cancelled"}:
        from hermes_db.repositories.kanban_workspaces import guard_live_task
        guard_live_task(conn, store, task_id)
    return conn.execute(update(tasks).where(key(store, task_id)).values(**encode_task(values))).rowcount


def event(conn, store, task_id, kind, payload=None, run_id=None):
    return conn.scalar(events.insert().values(**owner(store), task_id=encode_text(task_id), kind=encode_text(kind),
        payload=encode_text(json.dumps(payload, ensure_ascii=False)) if payload is not None else None,
        run_id=run_id, created_at=int(time.time())).returning(events.c.id))


def comment(conn, store, task_id, author, body, now):
    return conn.scalar(comments.insert().values(**owner(store), task_id=encode_text(task_id), author=encode_text(author),
        body=encode_text(body), created_at=now).returning(comments.c.id))


def link(conn, store, parent_id, child_id):
    from hermes_db.repositories.kanban_workspaces import guard_parent_link
    guard_parent_link(conn, store, parent_id, child_id)
    conn.execute(insert(links).values(**owner(store), parent_id=encode_text(parent_id),
        child_id=encode_text(child_id)).on_conflict_do_nothing())


def linked_ids(conn, store, task_id, *, parents):
    own, other = (links.c.child_id, links.c.parent_id) if parents else (links.c.parent_id, links.c.child_id)
    return [decode_text(value) for value in conn.scalars(select(other).where(scope(links, store),
             own == encode_text(task_id)).order_by(other))]


def history(conn, store, task_id):
    return [{**row, "kind": decode_text(row["kind"]), "payload": json.loads(decode_text(row["payload"]) or "{}")}
            for row in conn.execute(select(events).where(key(store, task_id, events)).order_by(events.c.id.desc())).mappings()]


def blocked_is_sticky(history):
    latest = next((row for row in history if row["kind"] in {"blocked", "unblocked"}), None)
    if latest and latest["kind"] == "blocked":
        return True
    unblocked = next((row["id"] for row in history if row["kind"] == "unblocked"), 0)
    trip = next((row for row in history if row["kind"] == "gave_up" and row["id"] > unblocked), None)
    return bool(trip and trip["payload"].get("sticky"))


def resume_status(history):
    kinds = {"blocked", "block_loop_detected", "dependency_wait", "gave_up", "unblocked", "changes_requested",
             "review_reopened", "status", "reclaimed", "stale", "timed_out", "crashed", "spawn_failed", "rate_limited"}
    row = next((row for row in history if row["kind"] in kinds), None)
    payload = row["payload"] if row else {}
    return "review" if any(payload.get(key) == "review" for key in ("resume_status", "retry_status", "source_status")) else "ready"
