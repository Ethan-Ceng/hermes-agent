"""Scoped Core reads for dashboards and restartable event cursors."""

from sqlalchemy import and_, func, select
from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban import tasks, events, links, comments, runs
from hermes_db.core.values import decode_text, encode_text


def latest_event_id(store):
    with store.read() as conn:
        return conn.scalar(select(func.coalesce(func.max(events.c.id), 0)).where(repo.scope(events, store)))


def events_after(store, cursor, *, limit=200, with_task=False):
    columns = [events.c[name] for name in ("id", "task_id", "run_id", "kind", "payload", "created_at")]
    statement = select(*columns).where(repo.scope(events, store), events.c.id > cursor)
    if with_task:
        statement = statement.add_columns(tasks.c.assignee, tasks.c.tenant).outerjoin(tasks,
            and_(tasks.c.store_id == events.c.store_id, tasks.c.board_id == events.c.board_id, tasks.c.id == events.c.task_id))
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(statement.order_by(events.c.id).limit(int(limit))).mappings()]


def tasks_by_ids(store, task_ids):
    ids = [encode_text(value) for value in dict.fromkeys(task_ids)]
    with store.read() as conn:
        return {decode_text(row["id"]): repo.decode_task(row) for row in conn.execute(
            select(tasks).where(repo.scope(tasks, store), tasks.c.id.in_(ids))).mappings()}


def board_rollups(store):
    from hermes_cli.kanban_db_queries import summarize_board
    with store.read() as conn:
        link_rows = [repo.decode_record(row) for row in conn.execute(select(links.c.parent_id, links.c.child_id)
            .where(repo.scope(links, store))).mappings()]
        comment_rows = [repo.decode_record(row) for row in conn.execute(select(comments.c.task_id, func.count().label("n"))
            .where(repo.scope(comments, store)).group_by(comments.c.task_id)).mappings()]
        children = [repo.decode_record(row) for row in conn.execute(select(links.c.parent_id.label("pid"), tasks.c.status.label("cstatus"))
            .join(tasks, and_(tasks.c.store_id == links.c.store_id, tasks.c.board_id == links.c.board_id, tasks.c.id == links.c.child_id))
            .where(repo.scope(links, store))).mappings()]
        tenants = [decode_text(value) for value in conn.scalars(select(tasks.c.tenant).where(repo.scope(tasks, store),
            tasks.c.tenant.is_not(None)).distinct().order_by(tasks.c.tenant))]
    return summarize_board(link_rows, comment_rows, children, tenants)


def board_status_counts(store):
    with store.read() as conn:
        return {decode_text(row.status): int(row.n) for row in conn.execute(select(tasks.c.status, func.count().label("n"))
            .where(repo.scope(tasks, store)).group_by(tasks.c.status))}


def active_worker_rows(store):
    statement = select(runs.c.id.label("run_id"), runs.c.task_id, tasks.c.title.label("task_title"),
        tasks.c.status.label("task_status"), tasks.c.assignee.label("task_assignee"),
        *[runs.c[name] for name in ("profile", "worker_pid", "started_at", "claim_lock", "claim_expires", "last_heartbeat_at", "max_runtime_seconds")])
    statement = statement.join(tasks, and_(tasks.c.store_id == runs.c.store_id, tasks.c.board_id == runs.c.board_id,
        tasks.c.id == runs.c.task_id)).where(repo.scope(runs, store), runs.c.ended_at.is_(None),
        runs.c.worker_pid.is_not(None), tasks.c.status == b"running").order_by(runs.c.started_at)
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(statement).mappings()]
