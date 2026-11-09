"""Scoped run reads; no physical file paths or native connection attributes."""

from sqlalchemy import func, select

from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo
from hermes_db.tables.kanban import tasks, runs, events
from hermes_db.core.values import encode_text, decode_text


def get_run(store, run_id):
    from hermes_cli.kanban_db import Run
    with store.read() as conn:
        row = run_repo.get(conn, store, run_id)
        return Run.from_row(row) if row is not None else None


def list_runs(store, task_id, *, include_active=True, state_type=None, state_name=None):
    from hermes_cli.kanban_db import Run
    if (state_type is None) ^ (state_name is None):
        raise ValueError("state_type and state_name must both be set or both omitted")
    if state_type is not None and state_type not in {"status", "outcome"}:
        raise ValueError("state_type must be 'status' or 'outcome'")
    query = select(runs).where(repo.key(store, task_id, runs))
    if not include_active:
        query = query.where(runs.c.ended_at.is_not(None))
    if state_type is not None:
        query = query.where(runs.c[state_type] == encode_text(state_name))
    with store.read() as conn:
        return [Run.from_row(repo.decode_record(row)) for row in conn.execute(query.order_by(runs.c.started_at, runs.c.id)).mappings()]


def latest_run(store, task_id):
    from hermes_cli.kanban_db import Run
    with store.read() as conn:
        row = conn.execute(select(runs).where(repo.key(store, task_id, runs))
            .order_by(runs.c.started_at.desc(), runs.c.id.desc()).limit(1)).mappings().one_or_none()
        return Run.from_row(repo.decode_record(row)) if row is not None else None


def latest_summaries(store, task_ids):
    ids = list(task_ids)
    ranked = select(runs.c.task_id, runs.c.summary, func.row_number().over(partition_by=runs.c.task_id,
        order_by=(func.coalesce(runs.c.ended_at, runs.c.started_at).desc(), runs.c.id.desc())).label("rank"))
    ranked = ranked.where(repo.scope(runs, store), runs.c.task_id.in_([encode_text(tid) for tid in ids]),
                          runs.c.summary.is_not(None), runs.c.summary != b"").subquery()
    with store.read() as conn:
        return {decode_text(tid): decode_text(summary) for tid, summary in conn.execute(select(ranked.c.task_id, ranked.c.summary)
                .where(ranked.c.rank == 1))}


def latest_summary(store, task_id):
    return latest_summaries(store, [task_id]).get(task_id)


def current_run_started_ats(store, task_ids):
    query = select(tasks.c.id, runs.c.started_at).join(runs,
        (tasks.c.store_id == runs.c.store_id) & (tasks.c.board_id == runs.c.board_id) &
        (tasks.c.id == runs.c.task_id) & (tasks.c.current_run_id == runs.c.id))
    with store.read() as conn:
        return {decode_text(tid): stamp for tid, stamp in conn.execute(query.where(repo.scope(tasks, store),
            tasks.c.id.in_([encode_text(tid) for tid in task_ids])))}


def _retry_status_for_run(store, task_id, run_id=None):
    with store.read() as conn:
        row = repo.get(conn, store, task_id)
        current = row["current_run_id"] if row is not None else None
        return run_repo.retry_status(conn, store, task_id, current if run_id is None else run_id)


def goal_run_status(store, task_id, expected_run_id=None):
    from hermes_cli.kanban_db import _RUN_OUTCOME_TERMINAL_STATUS
    with store.read() as conn:
        task = repo.get(conn, store, task_id)
        if task is None:
            return None
        if expected_run_id is not None:
            run = run_repo.get(conn, store, expected_run_id)
            outcome = run["outcome"] if run is not None and run["task_id"] == task_id else None
            terminal = _RUN_OUTCOME_TERMINAL_STATUS.get(outcome)
            if terminal is not None:
                return terminal
            if outcome is not None or task["current_run_id"] != int(expected_run_id):
                return "superseded"
        if task["status"] in {"ready", "todo"}:
            kind = conn.scalar(select(events.c.kind).where(repo.key(store, task_id, events)).order_by(events.c.id.desc()).limit(1))
            if kind == b"changes_requested":
                return "changes_requested"
        return task["status"]


def recent_profile_completions(store, profile, exclude_task_id, *, limit=5):
    query = select(tasks.c.id, tasks.c.title, runs.c.summary, runs.c.ended_at).join(runs,
        (tasks.c.store_id == runs.c.store_id) & (tasks.c.board_id == runs.c.board_id) & (tasks.c.id == runs.c.task_id))
    query = query.where(repo.scope(tasks, store), runs.c.profile == encode_text(profile),
                        runs.c.task_id != encode_text(exclude_task_id), runs.c.outcome == b"completed")
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(query.order_by(runs.c.ended_at.desc().nulls_last())
                .limit(int(limit))).mappings()]
