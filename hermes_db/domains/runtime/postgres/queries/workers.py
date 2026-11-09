"""Scoped worker assignment, receipt identity, and linked admission reads."""

import json

from sqlalchemy import cast, exists, func, or_, select

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.runtime import session_admissions, worker_executions, worker_receipts
from hermes_state_runtime import RuntimeStoreError


def where(scope, execution_id):
    return (worker_executions.c.store_id == scope.require_store_id(), worker_executions.c.execution_id == execution_id)


def execution(conn, scope, execution_id):
    row = conn.execute(select(worker_executions).where(*where(scope, execution_id))).mappings().one_or_none()
    return dict(row) if row else None


def public_row(row):
    return {key: value for key, value in row.items() if key not in ("store_id", "adoption_digest")}


def receipt(conn, scope, execution_id, sequence):
    return conn.execute(select(worker_receipts).where(worker_receipts.c.store_id == scope.require_store_id(),
        worker_receipts.c.execution_id == execution_id, worker_receipts.c.sequence == sequence)).mappings().one_or_none()


def assignment(conn, scope, execution_id, session_id, generation):
    row = execution(conn, scope, execution_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    if row["session_id"] != session_id:
        raise RuntimeStoreError("permission_denied")
    session = runtime.lock_target(conn, scope, session_id)
    if type(generation) is not int or row["generation"] != generation or session["runtime_generation"] != generation:
        raise RuntimeStoreError("stale_generation")
    return row


def receipt_assignment(conn, scope, execution_id, session_id, generation, sequence, digest):
    old = receipt(conn, scope, execution_id, sequence)
    if old and old["payload_digest"] == digest:
        moved = json.loads(old["result_json"]).get("worker_assignment")
        if moved and moved["parent"] == session_id:
            current = execution(conn, scope, execution_id)
            if current is None:
                raise RuntimeStoreError("not_found")
            return assignment(conn, scope, execution_id, current["session_id"], generation)
    return assignment(conn, scope, execution_id, session_id, generation)


def linked_admission(conn, scope, session_id, generation, epoch, statuses):
    if conn.dialect.name == "sqlite":
        members = func.json_each(session_admissions.c.lineage_json).table_valued("value").alias("members")
        in_lineage = exists(select(1).select_from(members).where(members.c.value == session_id))
    else:
        from sqlalchemy.dialects.postgresql import JSONB
        in_lineage = cast(session_admissions.c.lineage_json, JSONB).contains([session_id])
    rows = conn.execute(select(session_admissions).where(session_admissions.c.store_id == scope.require_store_id(),
        session_admissions.c.generation == generation, session_admissions.c.owner_epoch == epoch,
        session_admissions.c.status.in_(statuses), or_(session_admissions.c.target_session_id == session_id, in_lineage))
        .order_by(session_admissions.c.seq)).mappings().all()
    if len(rows) > 1:
        raise RuntimeStoreError("admission_conflict")
    return rows[0] if rows else None


def claim_origin(conn, scope, params):
    origin = conn.scalar(select(worker_receipts.c.assignment_parent).where(
        worker_receipts.c.store_id == scope.require_store_id(), worker_receipts.c.execution_id == params["execution_id"],
        worker_receipts.c.assignment_parent.is_not(None))
        .order_by(worker_receipts.c.sequence).limit(1))
    return origin or params["session_id"]


def retry_target(conn, scope, params):
    from hermes_state_keys import admission_fingerprint

    if params.get("operation") != "compression.publish":
        return params["session_id"]
    digest = admission_fingerprint(canonical_target=params["session_id"],
        payload={"operation": params["operation"], "payload": params["payload"]})
    row = receipt_assignment(conn, scope, params["execution_id"], params["session_id"],
        params["generation"], params["sequence"], digest)
    return row["session_id"]
