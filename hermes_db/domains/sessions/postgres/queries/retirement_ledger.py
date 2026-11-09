"""Retire terminal identities without retaining executable transcript copies."""

import json
import time

from sqlalchemy import select

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.runtime import session_admissions, worker_executions, worker_receipts
from hermes_state_keys import admission_fingerprint
from hermes_state_terminal import ADMISSION_PREFIX, RESULT_PREFIX, WORKER_PREFIX, encode_result, identity_key, load_result

TRANSCRIPT_FIELDS = frozenset({"messages", "last_reasoning", "tools", "_turn_user_row"})


def retire(conn, scope, session_ids):
    for sid in session_ids:
        admissions = conn.execute(select(session_admissions).where(runtime.target_where(scope, sid))).mappings().all()
        workers = conn.execute(select(worker_executions).where(worker_executions.c.store_id == scope.require_store_id(),
            worker_executions.c.session_id == sid)).mappings().all()
        for row in admissions:
            _retire_admission(conn, scope, row)
        for row in workers:
            _retire_worker(conn, scope, row)
        conn.execute(worker_executions.delete().where(worker_executions.c.store_id == scope.require_store_id(),
            worker_executions.c.session_id == sid))
        conn.execute(session_admissions.delete().where(runtime.target_where(scope, sid)))


def _retire_admission(conn, scope, raw):
    from hermes_db.domains.sessions.postgres.queries import media
    media.retire_admission(conn, scope, json.loads(raw["payload_json"]), raw["request_id"])
    row = {key: value for key, value in raw.items() if key != "store_id"}
    row.update(payload_json="{}", lineage_json="[]", retired_at=time.time())
    key = RESULT_PREFIX + row["admission_id"]
    saved = runtime.meta(conn, scope, key)
    if saved is not None:
        value = load_result(saved)
        result = value.get("result")
        if isinstance(result, dict):
            value["result"] = {**{key: item for key, item in result.items() if key not in TRANSCRIPT_FIELDS}, "messages": []}
        runtime.set_meta(conn, scope, key, json.dumps(encode_result(value), ensure_ascii=True, allow_nan=False))
    runtime.set_meta(conn, scope, ADMISSION_PREFIX + row["admission_id"], json.dumps(row, ensure_ascii=True))
    runtime.set_meta(conn, scope, identity_key(row["principal_id"], row["target_session_id"], row["request_id"]), json.dumps(row["admission_id"]))


def _retire_worker(conn, scope, raw):
    row = {key: value for key, value in raw.items() if key != "store_id"}
    where = (worker_receipts.c.store_id == scope.require_store_id(), worker_receipts.c.execution_id == row["execution_id"])
    receipts = [dict(item) for item in conn.execute(select(worker_receipts.c.sequence, worker_receipts.c.payload_digest,
        worker_receipts.c.result_json).where(*where).order_by(worker_receipts.c.sequence)).mappings()]
    closing = admission_fingerprint(canonical_target=row["session_id"], payload={"operation": "execution.finish", "payload": {}})
    for receipt in receipts:
        if receipt["payload_digest"] != closing:
            receipt["result_json"] = None
    row.update(receipts=receipts, retired_at=time.time())
    runtime.set_meta(conn, scope, WORKER_PREFIX + row["execution_id"], json.dumps(row, ensure_ascii=True))
    conn.execute(worker_receipts.delete().where(*where))
