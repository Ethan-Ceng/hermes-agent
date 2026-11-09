"""Load a consistent run snapshot and validate it while holding the Board fence."""

import json
from types import MappingProxyType

from sqlalchemy import func, select

from hermes_db.domains.kanban_evidence import TaskEvidence
from hermes_db.repositories import kanban as repo
from hermes_db.repositories import kanban_runs as run_repo
from hermes_db.tables.kanban import events, tasks
from hermes_db.core.values import decode_text


def snapshot(conn, store, task_id):
    task = repo.get(conn, store, task_id)
    if task is None:
        return None
    run = run_repo.get(conn, store, task["current_run_id"]) if task["current_run_id"] is not None else {}
    payloads = {}
    if task["current_run_id"] is not None:
        rows = conn.execute(select(events.c.kind, events.c.payload).where(repo.key(store, task_id, events),
            events.c.run_id == task["current_run_id"]).order_by(events.c.id)).mappings()
        for row in rows:
            try:
                payload = json.loads(decode_text(row["payload"]))
            except (ValueError, TypeError):
                payload = {}
            payloads[decode_text(row["kind"])] = payload if isinstance(payload, dict) else {}
    watermark = conn.scalar(select(func.max(events.c.id)).where(repo.key(store, task_id, events))) or 0
    return TaskEvidence(MappingProxyType(task), MappingProxyType(run or {}), MappingProxyType(payloads), watermark)


def running_snapshots(store):
    with store.read() as conn:
        ids = conn.scalars(select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.status == b"running")).all()
        return [snapshot(conn, store, decode_text(task_id)) for task_id in ids]


def unchanged(conn, store, evidence):
    current = snapshot(conn, store, evidence.task["id"])
    return (current is not None and current.task == evidence.task and current.run == evidence.run
            and current.event_watermark == evidence.event_watermark)
