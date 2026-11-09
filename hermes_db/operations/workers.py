"""Worker identity and the one receipt transaction; external effects stay on RPC."""

import hmac
import json

from sqlalchemy import select

from hermes_db.operations.effects import CoreEffect
from hermes_db.backends.postgresql.changes import track_changes
from hermes_db.repositories import runtime, workers as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.domains.sessions.postgres.queries.lineage import runtime_targets
from hermes_db.repositories.worker_retirement import compact_terminal
from hermes_db.tables.conversations import sessions as session_table
from hermes_db.tables.runtime import session_admissions, worker_executions, worker_receipts
from hermes_state_keys import admission_fingerprint
from hermes_state_runtime import RuntimeStoreError, _json, _secret_digest, _text


def register(conn, scope, *, epoch, execution_id, session_id, generation, kind, adoption_secret, require_idle=False):
    for value in (execution_id, session_id):
        _text(value)
    if kind not in ("cron", "child", "compute", "kanban"):
        raise RuntimeStoreError("invalid_params")
    digest = _secret_digest(adoption_secret)
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    session = runtime.lock_target(conn, scope, session_id)
    if type(generation) is not int or session["runtime_generation"] != generation:
        raise RuntimeStoreError("stale_generation")
    old = repo.execution(conn, scope, execution_id)
    if old:
        if (old["session_id"], old["generation"], old["kind"], old["owner_epoch"], old["adoption_digest"]) != (
                session_id, generation, kind, epoch, digest):
            raise RuntimeStoreError("admission_conflict")
        return repo.public_row(old)
    targets = runtime_targets(conn, scope, session_id)
    states = set(conn.execute(select(session_admissions.c.status).where(session_admissions.c.store_id == scope.require_store_id(),
        session_admissions.c.target_session_id.in_(targets), session_admissions.c.status.in_(("queued", "started", "unknown")))).scalars())
    if require_idle and states or runtime.worker_states(conn, scope, session_id):
        raise RuntimeStoreError("stale_generation")
    if "unknown" in states:
        raise RuntimeStoreError("unknown_execution")
    conn.execute(worker_executions.insert().values(store_id=scope.require_store_id(), execution_id=execution_id,
        session_id=session_id, kind=kind, status="registered", owner_epoch=epoch, generation=generation, adoption_digest=digest))
    return repo.public_row(repo.assignment(conn, scope, execution_id, session_id, generation))


def adopt(conn, scope, *, epoch, execution_id, session_id, generation, adoption_secret):
    digest = _secret_digest(adoption_secret)
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    row = repo.assignment(conn, scope, execution_id, session_id, generation)
    if row["status"] == "terminal":
        raise RuntimeStoreError("stale_generation")
    if not hmac.compare_digest(row["adoption_digest"], digest):
        raise RuntimeStoreError("permission_denied")
    if execution_id.startswith("admission-worker:") and row["owner_epoch"] != epoch:
        raise RuntimeStoreError("stale_epoch")
    linked = repo.linked_admission(conn, scope, session_id, generation, row["owner_epoch"], ("started", "unknown"))
    if linked:
        runtime.update(conn, scope, linked["admission_id"], owner_epoch=epoch, status="started")
    conn.execute(worker_executions.update().where(*repo.where(scope, execution_id)).values(owner_epoch=epoch, status="running"))
    return repo.public_row(repo.assignment(conn, scope, execution_id, session_id, generation))


def apply_receipt(conn, scope, *, epoch, execution_id, session_id, generation, sequence, operation, payload, handlers):
    if type(sequence) is not int or sequence < 1 or not isinstance(operation, str) or operation not in handlers:
        raise RuntimeStoreError("invalid_params")
    handler = handlers[operation]
    if not isinstance(handler, CoreEffect):
        raise TypeError("PostgreSQL worker handlers require an explicit CoreEffect")
    encoded = _json(payload)
    if len(encoded.encode("utf-8", errors="surrogatepass")) > 4 * 1024 * 1024:
        raise RuntimeStoreError("invalid_params")
    digest = admission_fingerprint(canonical_target=session_id, payload={"operation": operation, "payload": json.loads(encoded)})
    runtime.require_epoch(conn, scope, epoch)
    # Handlers may publish a new root, rename a global title or close a child.
    # Take the short exclusive map fence up front, never upgrade after a root.
    sessions.lock_store(conn, scope, exclusive=True)
    row = repo.receipt_assignment(conn, scope, execution_id, session_id, generation, sequence, digest)
    if row["owner_epoch"] != epoch:
        raise RuntimeStoreError("stale_epoch")
    old = repo.receipt(conn, scope, execution_id, sequence)
    if old:
        if old["payload_digest"] != digest:
            raise RuntimeStoreError("admission_conflict")
        from hermes_state_runtime_workers import retired_receipt
        if retired_receipt(old["result_json"]):
            raise RuntimeStoreError("stale_generation")
        return json.loads(old["result_json"])
    if row["status"] not in ("registered", "running"):
        raise RuntimeStoreError("stale_generation")
    if sequence != row["last_sequence"] + 1:
        raise RuntimeStoreError("invalid_params")
    with track_changes(conn) as changes:
        result = handler.apply(conn, scope, session_id, json.loads(encoded))
    _save_receipt(conn, scope, execution_id, sequence, digest, result)
    closing = operation == "execution.finish"
    conn.execute(worker_executions.update().where(*repo.where(scope, execution_id))
                 .values(last_sequence=sequence, status="terminal" if closing else "running"))
    if changes["changed"] or closing:
        sessions.update_session(conn, scope, session_id, {"runtime_revision": session_table.c.runtime_revision + 1})
    if closing:
        compact_terminal(conn, scope, execution_id)
    return result


def _save_receipt(conn, scope, execution_id, sequence, digest, result):
    encoded = json.dumps(result, ensure_ascii=True, allow_nan=False)
    snapshot = isinstance(result, dict) and ("messages" in result or "session" in result)
    candidate = result.get("title_candidate") if isinstance(result, dict) else None
    candidate = candidate.encode("utf-8", "surrogatepass") if isinstance(candidate, str) else None
    assignment = result.get("worker_assignment", {}) if isinstance(result, dict) else {}
    conn.execute(worker_receipts.insert().values(store_id=scope.require_store_id(), execution_id=execution_id,
        sequence=sequence, payload_digest=digest, result_json=encoded, read_snapshot=int(snapshot), title_candidate=candidate,
        assignment_parent=assignment.get("parent"), assignment_session=assignment.get("session_id")))
