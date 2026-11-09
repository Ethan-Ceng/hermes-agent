"""Canonical epoch, FIFO admission and terminal transactions on Core connections."""

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.operations.effects import invoke
from hermes_db.repositories import runtime as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import messages, sessions as session_table
from hermes_db.tables.runtime import runtime_epoch, session_admissions, worker_executions
from hermes_state_keys import admission_fingerprint
from hermes_state_runtime import ADMISSION_QUEUE_MAX, ADMITTED_REQUEST_CONFLICT, RuntimeStoreError, _json, _text

ANY_HEAD = object()


def begin_epoch(conn, scope, instance_id):
    _text(instance_id)
    statement = insert(runtime_epoch).values(store_id=scope.require_store_id(), singleton=1, epoch=1, instance_id=instance_id)
    return conn.scalar(statement.on_conflict_do_update(index_elements=list(runtime_epoch.primary_key.columns),
        set_={"epoch": runtime_epoch.c.epoch + 1, "instance_id": statement.excluded.instance_id}).returning(runtime_epoch.c.epoch))


def admit(conn, scope, *, epoch, principal_id, session_id, request_id, payload, intent="queue",
          _authorize_write=None, _replay_guard=None):
    for value in (principal_id, session_id, request_id):
        _text(value)
    if intent not in ("queue", "steer", "redirect"):
        raise RuntimeStoreError("invalid_params")
    encoded = _json(payload)
    digest = admission_fingerprint(canonical_target=session_id, payload={"input": json.loads(encoded), "intent": intent})
    repo.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope)
    if principal_id == "api":
        repo.lock_api_request(conn, scope, request_id)
    retired = _retired_replay(conn, scope, principal_id, session_id, request_id, digest)
    if retired is not None:
        return retired
    repo.lock_target(conn, scope, session_id)
    old = repo.find(conn, scope, principal_id, session_id, request_id)
    if old:
        if old["payload_digest"] != digest:
            raise RuntimeStoreError("admission_conflict", **ADMITTED_REQUEST_CONFLICT)
        invoke(_replay_guard, conn, scope)
        return repo.public_row(old)
    count = conn.scalar(select(func.count()).select_from(session_admissions).where(repo.target_where(scope, session_id),
        session_admissions.c.status == "queued"))
    if count >= ADMISSION_QUEUE_MAX:
        raise RuntimeStoreError("queue_full")
    invoke(_authorize_write, conn, scope)
    admission_id = uuid.uuid4().hex
    repo.insert_admission(conn, scope, dict(admission_id=admission_id, request_id=request_id, principal_id=principal_id,
        target_session_id=session_id, lineage_json=json.dumps([session_id]), payload_json=encoded, payload_digest=digest,
        intent=intent, status="queued", owner_epoch=epoch))
    return repo.public_row(repo.admission(conn, scope, admission_id))


def _retired_replay(conn, scope, principal_id, session_id, request_id, digest):
    from hermes_state_mutation_retirement import RETIRED_PREFIX
    from hermes_state_terminal import identity_key
    if repo.meta(conn, scope, RETIRED_PREFIX + session_id) is None:
        return None
    saved = repo.meta(conn, scope, identity_key(principal_id, session_id, request_id))
    if saved is None:
        raise RuntimeStoreError("not_found")
    old = repo.admission(conn, scope, json.loads(saved))
    if old is None:
        raise RuntimeStoreError("not_found")
    if old["payload_digest"] != digest:
        raise RuntimeStoreError("admission_conflict", **ADMITTED_REQUEST_CONFLICT)
    return repo.public_row(old)


def claim(conn, scope, *, epoch, session_id, _guard=None, head=ANY_HEAD):
    repo.require_epoch(conn, scope, epoch)
    session = repo.lock_target(conn, scope, session_id)
    invoke(_guard, conn, scope)
    blocked = set(conn.execute(select(session_admissions.c.status).where(repo.target_where(scope, session_id),
        session_admissions.c.status.in_(("started", "unknown")))).scalars())
    workers = repo.worker_states(conn, scope, session_id)
    if "unknown" in blocked or "unknown" in workers:
        raise RuntimeStoreError("unknown_execution")
    if blocked or workers:
        return None
    row = conn.execute(select(session_admissions).where(repo.target_where(scope, session_id), session_admissions.c.status == "queued")
        .order_by(session_admissions.c.seq).limit(1).with_for_update()).mappings().one_or_none()
    if head is not ANY_HEAD and (row["admission_id"] if row else None) != head:
        return False
    if row is None:
        return None
    generation = session["runtime_generation"] + 1
    sessions.update_session(conn, scope, session_id, {"runtime_generation": generation})
    repo.update(conn, scope, row["admission_id"], status="started", owner_epoch=epoch, generation=generation)
    result = repo.public_row(repo.admission(conn, scope, row["admission_id"]))
    # Only this FIFO's lineage matters. The root lock precedes both IDs and
    # this mark, so another lineage's pending sequence never defines our turn.
    from hermes_db.domains.sessions.postgres.queries.lineage import runtime_targets
    peer_ids = runtime_targets(conn, scope, session_id)
    result["transcript_mark"] = conn.scalar(select(func.coalesce(func.max(messages.c.id), 0)).where(
        messages.c.store_id == scope.require_store_id(), messages.c.session_id.in_(peer_ids)))
    return result


def cancel(conn, scope, *, epoch, admission_id):
    repo.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope)
    existing = repo.admission(conn, scope, admission_id)
    if existing and existing["status"] == "terminal" and existing["outcome"] != "steering":
        return repo.public_row(existing)
    row, _ = repo.lock_admission(conn, scope, admission_id)
    if row["status"] == "unknown":
        raise RuntimeStoreError("unknown_execution")
    if row["status"] == "started" or row["outcome"] == "steering":
        raise RuntimeStoreError("stale_generation")
    if row["status"] == "queued":
        repo.update(conn, scope, admission_id, status="terminal", outcome="cancelled")
    return repo.public_row(repo.admission(conn, scope, admission_id))


def settle(conn, scope, *, epoch, admission_id, generation, outcome, result=None, _transfers=None, _terminal_write=None):
    if outcome not in ("completed", "interrupted", "rejected", "failed"):
        raise RuntimeStoreError("invalid_params")
    repo.require_epoch(conn, scope, epoch)
    # A terminal write also retires delegated executions on independent roots.
    # Fence the mapping before any root lock, so their concurrent writers finish
    # before this short transaction closes children and compacts read receipts.
    sessions.lock_store(conn, scope, exclusive=True)
    row, session = repo.lock_admission(conn, scope, admission_id)
    if row["status"] != "started" or row["owner_epoch"] != epoch or type(generation) is not int or row["generation"] != generation or session["runtime_generation"] != generation:
        raise RuntimeStoreError("stale_generation")
    _retire_workers(conn, scope, row, epoch)
    invoke(_terminal_write, conn, scope, row)
    if result is not None:
        from hermes_state_terminal import RESULT_PREFIX, compact_result, encode_result
        encoded = _json(encode_result(compact_result(result, user_message=json.loads(row["payload_json"]).get("text"))))
        repo.set_meta(conn, scope, RESULT_PREFIX + admission_id, encoded)
    repo.update(conn, scope, admission_id, status="terminal", outcome=outcome)
    settle_transfers(conn, scope, epoch, generation, _transfers, outcome, row["target_session_id"])
    sessions.update_session(conn, scope, row["target_session_id"], {"runtime_revision": session_table.c.runtime_revision + 1})
    return repo.public_row(repo.admission(conn, scope, admission_id))


def _retire_workers(conn, scope, row, epoch):
    lineage = json.loads(row["lineage_json"])
    targets = {row["target_session_id"], lineage[-1] if lineage else row["target_session_id"]}
    from hermes_db.repositories.worker_retirement import compact_terminal
    live = conn.execute(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id.in_(targets), worker_executions.c.generation == row["generation"],
        worker_executions.c.owner_epoch == epoch, worker_executions.c.status != "terminal")).scalars().all()
    for execution_id in live:
        compact_terminal(conn, scope, execution_id)
    conn.execute(worker_executions.update().where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id.in_(targets), worker_executions.c.generation == row["generation"],
        worker_executions.c.owner_epoch == epoch).values(status="terminal"))


def settle_transfers(conn, scope, epoch, generation, transfers, outcome, target_session_id):
    for admission_id, delivered in (transfers or {}).items():
        conditions = (repo.admission_where(scope, admission_id), session_admissions.c.status == "terminal",
            session_admissions.c.outcome == "steering", session_admissions.c.owner_epoch == epoch,
            session_admissions.c.generation == generation, session_admissions.c.target_session_id == target_session_id)
        values = {"outcome": "steered" if outcome == "completed" else "interrupted"} if delivered else {
            "status": "queued", "outcome": None, "generation": None}
        conn.execute(session_admissions.update().where(*conditions).values(**values))


def mark_unknown(conn, scope, *, epoch, admission_id, generation, transfers=None):
    repo.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    row, _ = repo.lock_admission(conn, scope, admission_id)
    if row["owner_epoch"] != epoch or row["generation"] != generation:
        raise RuntimeStoreError("stale_generation")
    if row["status"] in {"terminal", "unknown"}:
        return row["status"]
    if row["status"] != "started":
        raise RuntimeStoreError("stale_generation")
    repo.update(conn, scope, admission_id, status="unknown")
    settle_transfers(conn, scope, epoch, generation, transfers, "unknown", row["target_session_id"])
    sessions.update_session(conn, scope, row["target_session_id"], {"runtime_revision": session_table.c.runtime_revision + 1})
    return "unknown"


def steer(conn, scope, *, epoch, admission_id, generation):
    repo.require_epoch(conn, scope, epoch)
    row, _ = repo.lock_admission(conn, scope, admission_id)
    if row["status"] == "terminal" and row["outcome"] in ("steering", "steered"):
        return repo.public_row(row), False
    if row["status"] != "queued":
        raise RuntimeStoreError("admission_started")
    if type(generation) is not int:
        raise RuntimeStoreError("session_idle")
    started = conn.scalar(select(session_admissions.c.admission_id).where(repo.target_where(scope, row["target_session_id"]),
        session_admissions.c.status == "started", session_admissions.c.owner_epoch == epoch, session_admissions.c.generation == generation).limit(1))
    if started is None:
        raise RuntimeStoreError("session_idle")
    repo.update(conn, scope, admission_id, status="terminal", outcome="steering", owner_epoch=epoch, generation=generation)
    return repo.public_row(repo.admission(conn, scope, admission_id)), True


def revert_steer(conn, scope, *, epoch, admission_id, generation):
    repo.require_epoch(conn, scope, epoch)
    repo.lock_admission(conn, scope, admission_id)
    return conn.execute(session_admissions.update().where(repo.admission_where(scope, admission_id),
        session_admissions.c.status == "terminal", session_admissions.c.outcome == "steering",
        session_admissions.c.owner_epoch == epoch, session_admissions.c.generation == generation)
        .values(status="queued", outcome=None, generation=None)).rowcount == 1


def recover(conn, scope, *, epoch):
    repo.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    from hermes_db.repositories.worker_retirement import retire_stale_children
    retire_stale_children(conn, scope, epoch)
    conn.execute(worker_executions.update().where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.status.in_(("registered", "running")), worker_executions.c.owner_epoch != epoch).values(status="unknown"))
    conn.execute(session_admissions.update().where(session_admissions.c.store_id == scope.require_store_id(),
        session_admissions.c.status == "terminal", session_admissions.c.outcome == "steering",
        session_admissions.c.owner_epoch != epoch).values(outcome="interrupted"))
    return conn.execute(session_admissions.update().where(session_admissions.c.store_id == scope.require_store_id(),
        session_admissions.c.status == "started", session_admissions.c.owner_epoch != epoch).values(status="unknown")).rowcount


def resolve_unknown(conn, scope, *, epoch, admission_id, generation, _terminal_write=None, _captured=None):
    from hermes_state_terminal import RESULT_PREFIX, compact_result, encode_result

    repo.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    row = repo.admission(conn, scope, admission_id)
    if row is None:
        raise RuntimeStoreError("not_found")
    if type(generation) is int and row["generation"] == generation and row["status"] == "terminal" and (
            row["outcome"] == "interrupted" or repo.meta(conn, scope, RESULT_PREFIX + admission_id) is not None):
        return repo.public_row(row)
    row, _ = repo.lock_admission(conn, scope, admission_id)
    if type(generation) is not int or row["status"] != "unknown" or row["generation"] != generation:
        raise RuntimeStoreError("stale_generation")
    outcome = "interrupted"
    if _captured is not None and row["owner_epoch"] == epoch:
        outcome, stored = _captured
        if outcome not in ("completed", "interrupted", "failed"):
            raise RuntimeStoreError("invalid_params")
        repo.set_meta(conn, scope, RESULT_PREFIX + admission_id, _json(encode_result(compact_result(
            stored, user_message=json.loads(row["payload_json"]).get("text")))))
    invoke(_terminal_write, conn, scope, row)
    _retire_workers(conn, scope, row, row["owner_epoch"])
    repo.update(conn, scope, admission_id, status="terminal", outcome=outcome)
    sessions.update_session(conn, scope, row["target_session_id"], {"runtime_revision": session_table.c.runtime_revision + 1})
    return repo.public_row(repo.admission(conn, scope, admission_id))
