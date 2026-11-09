"""Private terminal evidence in the owning store, with no history reconstruction."""

import hmac
import json

from sqlalchemy import select

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.runtime import state_meta
from hermes_db.domains.runtime.values import RuntimeStoreError, _secret_digest
from hermes_db.domains.runtime.receipts import ADMISSION_PREFIX, RESULT_PREFIX, WORKER_PREFIX, load_result


def admission(conn, scope, admission_id):
    raw = runtime.meta(conn, scope, ADMISSION_PREFIX + admission_id)
    return json.loads(raw) if raw is not None else None


def api_admissions(conn, scope, request_id):
    rows = conn.execute(select(state_meta.c.value).where(state_meta.c.store_id == scope.require_store_id(),
        state_meta.c.key.startswith(ADMISSION_PREFIX, autoescape=True))).scalars()
    return [row for raw in rows if (row := json.loads(raw))["principal_id"] == "api" and row["request_id"] == request_id]


def result(conn, scope, admission_id):
    raw = runtime.meta(conn, scope, RESULT_PREFIX + admission_id)
    return load_result(raw) if raw is not None else None


def worker_receipt(conn, scope, *, execution_id, session_id, generation, sequence, adoption_secret, payload_digest):
    proof = _secret_digest(adoption_secret)
    raw = runtime.meta(conn, scope, WORKER_PREFIX + execution_id)
    if raw is None:
        raise RuntimeStoreError("not_found")
    worker = json.loads(raw)
    if worker["session_id"] != session_id or not hmac.compare_digest(worker["adoption_digest"], proof):
        raise RuntimeStoreError("permission_denied")
    if type(generation) is not int or generation != worker["generation"]:
        raise RuntimeStoreError("stale_generation")
    receipt = next((row for row in worker["receipts"] if row["sequence"] == sequence), None)
    if receipt is None:
        raise RuntimeStoreError("stale_generation")
    if receipt["payload_digest"] != payload_digest:
        raise RuntimeStoreError("admission_conflict")
    if receipt["result_json"] is None:
        raise RuntimeStoreError("stale_generation")
    return json.loads(receipt["result_json"])
