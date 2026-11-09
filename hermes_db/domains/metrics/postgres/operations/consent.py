"""Consent intervals keep the existing clock-poison and rollback clamps."""

import uuid
from datetime import timedelta
from sqlalchemy import case, exists, select, update
from hermes_db.domains.metrics.postgres.queries import metrics as repo
from hermes_db.tables.metrics import marks, windows, packages


def reconcile(conn, store, enabled, now):
    from hermes_cli.observability.shared_metrics import _isoformat
    from hermes_cli.observability.shared_metrics_sender import MAX_OBS_ADVANCE_SECONDS, _parse_stamp
    raw = stamp = _isoformat(now)
    previous = conn.scalar(select(marks.c.stamp).where(repo.key(marks, store, {"name": "obs"})))
    if previous is not None:
        stamp = min(stamp, _isoformat(_parse_stamp(previous) + timedelta(seconds=MAX_OBS_ADVANCE_SECONDS)))
    repo.advance_mark(conn, store, "obs", stamp)
    current = dict(conn.execute(select(marks.c.name, marks.c.stamp).where(repo.scope(marks, store))).all())
    row = conn.execute(select(windows).where(repo.scope(windows, store), windows.c.closed_at.is_(None))).mappings().one_or_none()
    if enabled and row is None:
        opened = max(value for value in (current["obs"], current.get("data")) if value is not None)
        conn.execute(windows.insert().values(store_id=store.scope.require_store_id(), window_id=str(uuid.uuid4()), opened_at=opened, last_confirmed_at=opened))
    elif row is not None:
        fields = {"last_confirmed_at": max(row["last_confirmed_at"], current["obs"])} if enabled else {"closed_at": min(row["last_confirmed_at"], raw)}
        conn.execute(update(windows).where(repo.key(windows, store, {"window_id": row["window_id"]})).values(**fields))


def gate():
    return exists(select(1).where(windows.c.store_id == packages.c.store_id, packages.c.period_start >= windows.c.opened_at,
        packages.c.period_end <= case((windows.c.closed_at.is_(None), windows.c.last_confirmed_at), else_=windows.c.closed_at)))


def consented_day(conn, store, start):
    return conn.scalar(select(windows.c.window_id).where(repo.scope(windows, store), windows.c.closed_at.is_(None), windows.c.opened_at <= start).limit(1)) is not None
