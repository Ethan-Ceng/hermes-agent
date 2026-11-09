"""Scoped dispatch reads and small named diagnostic/default-assignment writes."""

import time

from sqlalchemy import func, select

from hermes_db.domains.kanban.postgres.queries import kanban as repo
from hermes_db.tables.kanban import comments, events, runs, tasks
from hermes_db.core.values import decode_text


def _running_per_profile(store):
    with store.read() as conn:
        return {decode_text(row.assignee): int(row.n) for row in conn.execute(
            select(tasks.c.assignee, func.count().label("n")).where(repo.scope(tasks, store),
                tasks.c.status == b"running", tasks.c.assignee.is_not(None)).group_by(tasks.c.assignee))}


def count_running_tasks(store):
    with store.read() as conn:
        return conn.scalar(select(func.count()).select_from(tasks).where(repo.scope(tasks, store), tasks.c.status == b"running"))


def _count_other_running(store, board=None):
    with store.read() as conn:
        return conn.scalar(select(func.count()).select_from(tasks).where(tasks.c.store_id == store.scope.require_store_id(),
            tasks.c.board_id != store.board_id, tasks.c.status == b"running"))


def _lane_rows(store, status):
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(select(tasks.c.id, tasks.c.assignee).where(
            repo.scope(tasks, store), tasks.c.status == status.encode(), tasks.c.claim_lock.is_(None)).order_by(
                tasks.c.priority.desc(), tasks.c.created_at.asc().nulls_first(), tasks.c.id)).mappings()]


def _has_spawnable(store, status):
    from hermes_cli.kanban_db_dispatch import _profile_exists_fn
    rows = _lane_rows(store, status)
    exists = _profile_exists_fn()
    return any(row["assignee"] is not None and (exists is None or exists(row["assignee"])) for row in rows)


def _apply_default_assignee(store, task_id, assignee, *, dry_run):
    if dry_run:
        return True
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task["status"] != "ready" or task["claim_lock"] is not None:
            return False
        if task["assignee"]:
            return task["assignee"] == assignee
        repo.task_update(conn, store, task_id, assignee=assignee)
        repo.event(conn, store, task_id, "assigned", {"assignee": assignee, "source": "kanban.default_assignee"})
    return True


def diagnostic(store, task_id, kind, payload, *, once=False):
    with store.write() as conn:
        if repo.get(conn, store, task_id) is None:
            return
        if once:
            history = repo.history(conn, store, task_id)
            if history and history[0]["kind"] == kind and history[0]["payload"] == payload:
                return
        repo.event(conn, store, task_id, kind, payload)


def _guard_history(conn, store, task_id, now):
    from hermes_cli import kanban_db_dispatch as dispatch
    success_cutoff = now - dispatch._RESPAWN_GUARD_SUCCESS_WINDOW
    pr_cutoff = now - dispatch._RESPAWN_GUARD_PR_WINDOW
    successes = [(row.ended_at, {}) for row in conn.execute(select(runs.c.ended_at).where(repo.key(store, task_id, runs),
        runs.c.outcome == b"completed", runs.c.ended_at >= success_cutoff))]
    event_rows = [(row["created_at"], repo.decode_record(row)) for row in conn.execute(select(events).where(
        repo.key(store, task_id, events), events.c.created_at >= min(success_cutoff, pr_cutoff))).mappings()]
    comment_rows = [(row["created_at"], repo.decode_record(row)) for row in conn.execute(select(comments).where(
        repo.key(store, task_id, comments), comments.c.created_at >= pr_cutoff)).mappings()]
    return successes, event_rows, comment_rows


def check_respawn_guard(store, task_id, *, lane="ready"):
    from hermes_cli.kanban_respawn_policy import primary_guard, history_guard
    now = int(time.time())
    with store.read() as conn:
        task = repo.get(conn, store, task_id)
        if task is None:
            return None
        latest = conn.execute(select(runs).where(repo.key(store, task_id, runs), runs.c.ended_at.is_not(None)).order_by(
            runs.c.ended_at.desc(), runs.c.id.desc()).limit(1)).mappings().one_or_none()
        handled, reason = primary_guard(task["last_failure_error"], repo.decode_record(latest) if latest else None, lane, now)
        if handled:
            return reason
        history = _guard_history(conn, store, task_id, now)
    return history_guard(*history)
