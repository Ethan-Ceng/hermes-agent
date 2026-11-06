"""Scoped delegation ledger rows; callers own transactions and authority."""

from sqlalchemy import and_, select

from hermes_db.tables.gateway import async_delegations
from hermes_state_runtime import RuntimeStoreError


def where(scope, delegation_id):
    return and_(async_delegations.c.store_id == scope.require_store_id(), async_delegations.c.delegation_id == delegation_id)


def get(conn, scope, delegation_id):
    row = conn.execute(select(async_delegations).where(where(scope, delegation_id))).mappings().one_or_none()
    return dict(row) if row else None


def owned(conn, scope, session_id, execution_id, delegation_id):
    from gateway.session_worker_delegation import _text
    _text(delegation_id)
    row = get(conn, scope, delegation_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    if row["parent_session_id"] != session_id or row["owner_execution_id"] != execution_id:
        raise RuntimeStoreError("permission_denied")
    return row


def insert(conn, scope, values):
    conn.execute(async_delegations.insert().values(store_id=scope.require_store_id(), **values))


def update(conn, scope, delegation_id, values, *conditions):
    return conn.execute(async_delegations.update().where(where(scope, delegation_id), *conditions).values(**values)).rowcount
