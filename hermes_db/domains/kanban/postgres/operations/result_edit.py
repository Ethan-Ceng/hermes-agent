"""Completed-task backfills preserve and update the original run handoff."""

import json
from sqlalchemy import func, select

from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo
from hermes_db.tables.kanban import runs


def edit_result(store, task_id, *, title, body, priority, result, summary, metadata, board):
    from hermes_cli import kanban_db as kb
    values = {name: value for name, value in (("title", title), ("body", body), ("priority", priority), ("result", result)) if value is not None}
    changed = list(values) + ["summary"] + (["metadata"] if metadata is not None else [])
    handoff = summary if summary is not None else result
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task["status"] != "done":
            return False
        repo.task_update(conn, store, task_id, **values)
        if priority is not None:
            repo.event(conn, store, task_id, "reprioritized", {"priority": priority})
        run_id = conn.scalar(select(runs.c.id).where(repo.key(store, task_id, runs), runs.c.outcome == b"completed")
            .order_by(func.coalesce(runs.c.ended_at, runs.c.started_at, 0).desc(), runs.c.id.desc()).limit(1))
        if run_id is None:
            run_id = run_repo.synthesize(conn, store, task, outcome="completed", summary=handoff, metadata=metadata)
        else:
            updates = {"summary": handoff}
            if metadata is not None:
                updates["metadata"] = json.dumps(metadata, ensure_ascii=False)
            run_repo.update_run(conn, store, run_id, **updates)
        fields = ["result", "summary"] + (["metadata"] if metadata is not None else [])
        repo.event(conn, store, task_id, "edited", {"fields": fields, "result_len": len(result) if result else 0,
                   "summary": kb._first_line(handoff, 400) or None}, run_id)
    kb.notify_task_updated(store, task_id, changed, board=board)
    return True
