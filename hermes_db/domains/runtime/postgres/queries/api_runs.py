"""Run identity records scoped by stable store id and authenticated API scope."""

from sqlalchemy import and_, or_, select

from hermes_db.tables.api import run_idempotency as table
from gateway.platforms.api_server_run_idempotency import TERMINAL_STATUSES, _encode_status, _record


def where(scope, api_scope):
    return and_(table.c.store_id == scope.require_store_id(), table.c.scope == api_scope)


def record(row):
    return _record(row["run_id"], row["status_json"], row["owner_pid"], row["owner_started"], row["updated_at"])


def find(conn, scope, api_scope, key):
    row = conn.execute(select(table).where(where(scope, api_scope), table.c.idempotency_key == key)).mappings().one_or_none()
    return dict(row) if row else None


def insert(conn, scope, api_scope, key, fingerprint, run_id, status, owner_pid, owner_started, retention, now):
    conn.execute(table.insert().values(store_id=scope.require_store_id(), scope=api_scope, idempotency_key=key,
        fingerprint=fingerprint, run_id=run_id, status_json=_encode_status(status), owner_pid=int(owner_pid or 0),
        owner_started=int(owner_started or 0), retention_until=retention, created_at=now, updated_at=now))


def extend(conn, scope, api_scope, until, *conditions):
    return conn.execute(table.update().where(where(scope, api_scope), *conditions, table.c.retention_until < until)
        .values(retention_until=until)).rowcount


def prune(conn, scope, api_scope, now, retention_seconds, acknowledged_seconds):
    import json
    expired = or_(table.c.acknowledged_at <= now - acknowledged_seconds,
        (table.c.retention_until > 0) & (table.c.retention_until <= now),
        (table.c.retention_until <= 0) & (table.c.updated_at < now - retention_seconds))
    rows = conn.execute(select(table.c.idempotency_key, table.c.status_json).where(where(scope, api_scope), expired)).all()
    for key, encoded in rows:
        if json.loads(encoded).get("status") in TERMINAL_STATUSES:
            conn.execute(table.delete().where(where(scope, api_scope), table.c.idempotency_key == key))
