"""Prune only terminal tasks whose outcomes are durable canonical publications."""

from sqlalchemy import delete, select
from gateway import hosted_room_driver as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, work as room_work
from hermes_db.tables.room_runs import tasks


def prune_published_terminal_tasks(store, *, room_id, clock, retention_seconds=native.TERMINAL_TASK_RETENTION_SECONDS,
                                   retain=native.MAX_RETAINED_TERMINAL_TASKS):
    room_id = native._identifier(room_id, label="room_id")
    now = native._timestamp(clock)
    if retention_seconds <= 0:
        raise native.DriverValidationError("retention_seconds must be positive")
    native._bounded_int(retain, message="retain must be a non-negative integer")
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        rows = conn.execute(select(tasks.c.task_id, tasks.c.terminal_at).where(room_repo.scope(tasks, store, room_id),
            tasks.c.status.in_(native.TERMINAL_STATUSES), ~room_work.unpublished(tasks, store)).order_by(
                tasks.c.terminal_at.desc(), tasks.c.task_id)).mappings()
        cutoff = now - float(retention_seconds)
        selected = [row["task_id"] for index, row in enumerate(rows)
                    if index >= retain or (row["terminal_at"] is not None and row["terminal_at"] <= cutoff)][:native.MAX_TASK_PRUNE_BATCH]
        if not selected:
            return 0
        return max(0, conn.execute(delete(tasks).where(room_repo.scope(tasks, store, room_id), tasks.c.task_id.in_(selected))).rowcount)
