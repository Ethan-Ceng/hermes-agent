"""Scoped runtime rows and epoch/root locking; never commits."""

import json

from sqlalchemy import and_, insert, select
from sqlalchemy.dialects.postgresql import insert as upsert

from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.runtime import runtime_epoch, session_admissions, state_meta, worker_executions
from hermes_db.domains.runtime.values import RuntimeStoreError


def admission_where(scope, admission_id):
    return and_(session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.admission_id == admission_id)


def target_where(scope, session_id):
    return and_(session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.target_session_id == session_id)


def require_epoch(conn, scope, epoch):
    current = conn.scalar(select(runtime_epoch.c.epoch).where(runtime_epoch.c.store_id == scope.require_store_id(),
        runtime_epoch.c.singleton == 1).with_for_update(read=True))
    if type(epoch) is not int or current is None or current != epoch:
        raise RuntimeStoreError("stale_epoch")


def lock_api_request(conn, scope, request_id):
    import hashlib
    # Different targets have different root locks. This stable control row
    # serializes their single-target API guard without serializing the store.
    key = "hermes:api-request-lock:" + hashlib.sha256(request_id.encode()).hexdigest()
    conn.execute(upsert(state_meta).values(store_id=scope.require_store_id(), key=key)
        .on_conflict_do_nothing(index_elements=list(state_meta.primary_key.columns)))
    conn.execute(select(state_meta.c.key).where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key == key).with_for_update()).one()


def lock_target(conn, scope, session_id):
    from hermes_db.domains.sessions.postgres.queries.lineage import runtime_targets
    from hermes_db.tables.conversations import sessions as session_table

    sessions.lock_store(conn, scope)
    row = sessions.raw_session(conn, scope, session_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    targets = runtime_targets(conn, scope, session_id)
    roots = conn.execute(select(session_table.c.lineage_root_id).where(session_table.c.store_id == scope.require_store_id(),
        session_table.c.id.in_(targets)).distinct()).scalars().all()
    for root in sorted(roots):
        sessions.lock_root(conn, scope, root)
    return sessions.raw_session(conn, scope, session_id)


def admission(conn, scope, admission_id):
    row = conn.execute(select(session_admissions).where(admission_where(scope, admission_id))).mappings().one_or_none()
    if row:
        return dict(row)
    from hermes_db.domains.runtime.receipts import ADMISSION_PREFIX
    saved = meta(conn, scope, ADMISSION_PREFIX + admission_id)
    return json.loads(saved) if saved else None


def lock_admission(conn, scope, admission_id):
    # Mapping is fenced before looking up the target: rehoming takes the
    # exclusive mapping lock, so waiting for a root cannot change this target.
    sessions.lock_store(conn, scope)
    row = admission(conn, scope, admission_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    target = lock_target(conn, scope, row["target_session_id"])
    return admission(conn, scope, admission_id), target


def find(conn, scope, principal_id, session_id, request_id):
    row = conn.execute(select(session_admissions).where(target_where(scope, session_id),
        session_admissions.c.principal_id == principal_id, session_admissions.c.request_id == request_id)).mappings().one_or_none()
    return dict(row) if row else None


def public_row(row):
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    for column in ("store_id", "payload_digest", "lineage_json", "retired_at"):
        result.pop(column, None)
    return result


def update(conn, scope, admission_id, **values):
    return conn.execute(session_admissions.update().where(admission_where(scope, admission_id)).values(**values)).rowcount


def insert_admission(conn, scope, values):
    conn.execute(insert(session_admissions).values(store_id=scope.require_store_id(), **values))


def worker_states(conn, scope, session_id):
    from hermes_db.domains.sessions.postgres.queries.lineage import runtime_targets
    return set(conn.execute(select(worker_executions.c.status).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id.in_(runtime_targets(conn, scope, session_id)),
        worker_executions.c.status.in_(("registered", "running", "unknown")))).scalars())


def meta(conn, scope, key):
    return conn.scalar(select(state_meta.c.value).where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key == key))


def set_meta(conn, scope, key, value):
    statement = upsert(state_meta).values(store_id=scope.require_store_id(), key=key, value=value)
    conn.execute(statement.on_conflict_do_update(index_elements=list(state_meta.primary_key.columns), set_={"value": statement.excluded.value}))
