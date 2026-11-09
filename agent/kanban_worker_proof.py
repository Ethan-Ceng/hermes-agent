"""Backend-specific authority carriers for the shared in-place recovery predicate."""

import os
from pathlib import Path


def adopted_claim_proof(task_id, db_path, run_id, claim_lock):
    from hermes_db.integration.kanban_worker import worker_binding
    binding = worker_binding()
    if binding is None:
        return None
    from agent.runtime_session_store import WorkerPersistenceError
    from gateway.session_kanban_pg_worker import claim_live
    context = binding[1]
    if (task_id != context["task_id"] or db_path is not None
            or (run_id is not None and str(run_id) != str(context["run_id"]))
            or (claim_lock is not None and claim_lock != context["claim_lock"])):
        return False
    try:
        return bool(claim_live())
    except WorkerPersistenceError:
        from agent.kanban_turn_recovery import logger
        logger.warning("kanban claim check: owner proof unavailable — not retrying in place")
        return False


def sqlite_claim_carrier(db_path, run_id, claim_lock):
    from agent import kanban_turn_recovery as recovery
    db_path = recovery._kanban_db_path() if db_path is None else (db_path.strip() or None)
    if not db_path or not Path(db_path).exists():
        recovery.logger.warning("kanban claim check: pinned board db %r not found — not retrying in place", db_path)
        return None
    run = str(run_id if run_id is not None else os.environ.get("HERMES_KANBAN_RUN_ID") or "").strip()
    lock = str(claim_lock if claim_lock is not None else os.environ.get("HERMES_KANBAN_CLAIM_LOCK") or "").strip()
    if not run or not lock:
        recovery.logger.warning("kanban claim check: missing dispatcher-pinned run-id/claim-lock carrier "
                                "— no exact authority to re-prove, not retrying in place")
        return None
    return db_path, run, lock
