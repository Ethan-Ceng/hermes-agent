"""Consistent scoped task/event/run/DAG inputs for fleet or single-card diagnostics."""

from sqlalchemy import select
from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban import tasks, events, runs
from hermes_db.core.values import encode_text


def diagnostic_snapshot(store, task_id=None, *, task_ids=None):
    condition = repo.key(store, task_id) if task_id is not None else repo.scope(tasks, store) & (tasks.c.status != b"archived")
    if task_ids is not None:
        condition = repo.scope(tasks, store) & tasks.c.id.in_([encode_text(value) for value in task_ids])
    with store.read() as conn:
        rows = [repo.decode_task(row) for row in conn.execute(select(tasks).where(condition)).mappings()]
        ids = [encode_text(row["id"]) for row in rows]
        by_table = {}
        for table in (events, runs):
            by = {row["id"]: [] for row in rows}
            records = conn.execute(select(table).where(repo.scope(table, store), table.c.task_id.in_(ids)).order_by(table.c.id)).mappings()
            for record in records:
                decoded = repo.decode_record(record)
                by[decoded["task_id"]].append(decoded)
            by_table[table.name] = by
        contexts = {}
        for row in rows:
            context = {"parents": [], "children": []}
            for bucket, parents in (("parents", True), ("children", False)):
                for linked in repo.linked_ids(conn, store, row["id"], parents=parents):
                    task = repo.require_task(conn, store, linked)
                    context[bucket].append({name: task[name] for name in ("id", "title", "status")})
            contexts[row["id"]] = context
    return [(row, by_table[events.name][row["id"]], by_table[runs.name][row["id"]], contexts[row["id"]]) for row in rows]
