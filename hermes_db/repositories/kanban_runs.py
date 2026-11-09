"""Run records and fences inside a caller-owned Board transaction."""

import json
import time
from sqlalchemy import and_, select, update

from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban import runs, events
from hermes_db.core.values import encode_text

TEXT_FIELDS = {"task_id", "profile", "step_key", "status", "claim_lock", "worker_started_at", "outcome", "summary", "metadata", "error"}
_UNSET = object()


def encode(values):
    return {name: encode_text(value) if name in TEXT_FIELDS else value for name, value in values.items()}


def key(store, run_id):
    return and_(repo.scope(runs, store), runs.c.id == int(run_id))


def get(conn, store, run_id):
    row = conn.execute(select(runs).where(key(store, run_id))).mappings().one_or_none()
    return repo.decode_record(row) if row is not None else None


def update_run(conn, store, run_id, **values):
    return conn.execute(update(runs).where(key(store, run_id)).values(**encode(values))).rowcount


def open_run(conn, store, task, lock, expires, now):
    values = dict(task_id=task["id"], profile=task["assignee"], step_key=task["current_step_key"],
                  status="running", claim_lock=lock, claim_expires=expires, max_runtime_seconds=task["max_runtime_seconds"], started_at=now)
    return conn.scalar(runs.insert().values(**repo.owner(store), **encode(values)).returning(runs.c.id))


def close_run(conn, store, task, *, outcome, status=None, summary=None, error=None, metadata=None):
    run_id = task["current_run_id"]
    if run_id is None:
        return None
    values = dict(status=status or outcome, outcome=outcome, summary=summary, error=error,
                  metadata=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
                  ended_at=int(time.time()), claim_expires=None)
    conn.execute(update(runs).where(key(store, run_id), runs.c.task_id == encode_text(task["id"]),
        runs.c.ended_at.is_(None)).values(**encode(values)))
    repo.task_update(conn, store, task["id"], current_run_id=None)
    return run_id


def retry_status(conn, store, task_id, run_id):
    if run_id is None:
        return "ready"
    payload = conn.scalar(select(events.c.payload).where(repo.key(store, task_id, events),
        events.c.run_id == int(run_id), events.c.kind == b"claimed").order_by(events.c.id.desc()).limit(1))
    from hermes_db.core.values import decode_text
    from hermes_cli.kanban_db import _json_dict
    data = _json_dict(decode_text(payload))
    return "review" if data.get("source_status") == "review" else "ready"


def synthesize(conn, store, task, *, outcome, summary=None, error=None, metadata=None, profile=_UNSET):
    now = int(time.time())
    values = dict(task_id=task["id"], profile=task["assignee"] if profile is _UNSET else profile,
        step_key=task["current_step_key"], status=outcome, outcome=outcome, summary=summary, error=error,
        metadata=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None, started_at=now, ended_at=now)
    return conn.scalar(runs.insert().values(**repo.owner(store), **encode(values)).returning(runs.c.id))
