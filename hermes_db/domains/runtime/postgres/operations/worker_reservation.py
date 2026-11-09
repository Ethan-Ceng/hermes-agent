"""Private owner reservations and loss fencing for an already-started admission."""

import json

from sqlalchemy import select

from gateway.owner_identity import same_owner
from hermes_db.domains.sessions.postgres.queries import lineage, sessions
from hermes_db.domains.runtime.postgres.queries import runtime, worker_retirement, workers
from hermes_db.tables.conversations import sessions as session_table
from hermes_db.tables.runtime import worker_executions
from hermes_state_keys import admission_fingerprint
from hermes_state_runtime import RuntimeStoreError, _secret_digest


def reserve(conn, scope, *, epoch, admission_id, principal_id, worker_subject, identity):
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    admission, owner = runtime.lock_admission(conn, scope, admission_id)
    if admission["status"] != "started" or admission["owner_epoch"] != epoch:
        raise RuntimeStoreError("producer_not_started")
    if not same_owner(admission["principal_id"], principal_id):
        raise RuntimeStoreError("permission_denied")
    generation = admission["generation"]
    if owner["runtime_generation"] != generation:
        raise RuntimeStoreError("stale_generation")
    sid = lineage.physical_target(conn, scope, admission["target_session_id"])
    execution_id = "admission-worker:" + admission_id
    if workers.execution(conn, scope, execution_id) is not None:
        raise RuntimeStoreError("admission_conflict")
    active = conn.scalar(select(worker_executions.c.execution_id).where(
        worker_executions.c.store_id == scope.require_store_id(), worker_executions.c.session_id == sid,
        worker_executions.c.status != "terminal").limit(1))
    if active is not None:
        raise RuntimeStoreError("stale_generation")
    sessions.lock_session(conn, scope, sid)
    sessions.update_session(conn, scope, sid, {"runtime_generation": generation})
    members = json.loads(admission["lineage_json"])
    if sid not in members:
        runtime.update(conn, scope, admission_id, lineage_json=json.dumps([*members, sid]))
    assignment = dict(identity, session_id=sid, execution_id=execution_id, generation=generation)
    claim = admission_fingerprint(canonical_target=sid, payload=assignment | {"principal": worker_subject or principal_id})
    conn.execute(worker_executions.insert().values(store_id=scope.require_store_id(), execution_id=execution_id,
        session_id=sid, kind="compute", owner_epoch=epoch, generation=generation, status="registered",
        adoption_digest=_secret_digest(claim)))
    return assignment | {"epoch": epoch}


def lose(conn, scope, *, epoch, admission_id, execution_id, generation):
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    admission, _ = runtime.lock_admission(conn, scope, admission_id)
    worker = workers.execution(conn, scope, execution_id)
    if (admission["status"] != "started" or admission["owner_epoch"] != epoch or admission["generation"] != generation
            or worker is None or worker["generation"] != generation or worker["owner_epoch"] != epoch):
        raise RuntimeStoreError("stale_generation")
    conn.execute(worker_executions.update().where(*workers.where(scope, execution_id)).values(status="terminal"))
    worker_retirement.compact_terminal(conn, scope, execution_id)
    runtime.update(conn, scope, admission_id, status="unknown")
    sessions.update_session(conn, scope, admission["target_session_id"],
        {"runtime_revision": session_table.c.runtime_revision + 1})
