"""Durable driver admissions and short, scoped task transactions."""

import dataclasses

from sqlalchemy import select

from gateway import hosted_room_driver as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, runs as repo
from hermes_db.tables.room_runs import tasks
from hermes_db.domains.rooms.postgres.operations.work import capture_transition_locked


def change(store, identity, *, now, fields, lease=None, lease_first=True, replay=None, guard=None):
    """All writers serialize on the scoped room lock before checking a task fence."""
    if lease is not None:
        native._check_same_room(lease, identity)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        if lease is not None and lease_first:
            repo.active_lease(conn, store, lease, now=now)
        row = repo.task(conn, store, identity)
        if replay is not None and (result := replay(row)) is not None:
            return result
        if lease is not None and not lease_first:
            repo.active_lease(conn, store, lease, now=now)
        if guard is not None:
            guard(row)
        repo.update_task(conn, store, identity, **fields)
        capture_transition_locked(conn, store, identity.room_id)
        return native._task_from_row(repo.task(conn, store, identity))


def admit_task(store, identity, *, payload, clock):
    normalized, encoded, digest = native._task_payload(payload)
    now = native._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_room(conn, store, identity.room_id)
        row = repo.task(conn, store, identity, required=False)
        if row is not None:
            if row["payload_digest"] != digest or row["payload_json"] != encoded:
                raise native.TaskConflictError("task_id is already bound to a different payload")
            return native._task_from_row(row, idempotent=True)
        bound = conn.scalar(select(tasks.c.task_id).where(room_repo.scope(tasks, store, identity.room_id),
            tasks.c.thread_id == identity.thread_id, tasks.c.turn_id == identity.turn_id))
        if bound is not None:
            raise native.TaskConflictError("thread_id and turn_id are already bound to a task")
        room_repo.insert_row(conn, store, tasks, dict(dataclasses.asdict(identity),
            source_event_seq=normalized["source_event_seq"], payload_json=encoded, payload_digest=digest,
            status="queued", execution_generation=0, cancel_generation=0, created_at=now, updated_at=now))
        capture_transition_locked(conn, store, identity.room_id)
        return native._task_from_row(repo.task(conn, store, identity))


def start_task(store, identity, lease, *, expected_cancel_generation, clock):
    native._check_same_room(lease, identity)
    native._cancel_generation(expected_cancel_generation)
    now = native._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_lease(conn, store, lease, now=now)
        row = repo.task(conn, store, identity)
        native._require_cancel_generation(row, expected_cancel_generation)
        if row["status"] != "queued":
            raise native.InvalidTaskTransitionError(f"cannot start task in state '{row['status']}'")
        ordered = repo.task_rows(conn, store, identity.room_id)
        if any(task["status"] in {"running", "indeterminate", "stopping"} for task in ordered):
            raise native.InvalidTaskTransitionError("room recovery must resolve the prior task before starting new work")
        queued = next((task for task in ordered if task["status"] == "queued"), None)
        if queued is None or queued["task_id"] != identity.task_id:
            raise native.InvalidTaskTransitionError("task is not next in the hosted room event order")
        generation = int(row["execution_generation"]) + 1
        repo.update_task(conn, store, identity, status="running", execution_generation=generation,
            run_gateway_id=lease.gateway_id, run_process_generation=lease.process_generation,
            run_lease_generation=lease.lease_generation, started_at=now, updated_at=now)
        capture_transition_locked(conn, store, identity.room_id)
        return native.TaskAttempt(identity, lease, generation, expected_cancel_generation)


def mark_attempt_indeterminate(store, attempt, lease, *, clock):
    native._check_same_room(lease, attempt.identity)
    now = native._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_lease(conn, store, lease, now=now)
        row = repo.task(conn, store, attempt.identity)
        if not native._generations_match(row, "running", attempt.execution_generation, attempt.cancel_generation):
            return
        repo.update_task(conn, store, attempt.identity, status="indeterminate", indeterminate_at=now, updated_at=now)
        capture_transition_locked(conn, store, lease.room_id)


def recover_room(store, lease, *, clock):
    now = native._timestamp(clock)
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        repo.active_lease(conn, store, lease, now=now)
        for row in repo.task_rows(conn, store, lease.room_id, "running"):
            if (row["run_gateway_id"], row["run_process_generation"], row["run_lease_generation"]) != native._run_fence(lease):
                repo.update_task(conn, store, native._task_identity_from_row(row),
                    status="indeterminate", indeterminate_at=now, updated_at=now)
        capture_transition_locked(conn, store, lease.room_id)
        return {status: [native._task_identity_from_row(row) for row in repo.task_rows(conn, store, lease.room_id, status)]
                for status in ("queued", "indeterminate")}


def get_task(store, identity):
    with store.read() as conn:
        return native._task_from_row(repo.task(conn, store, identity, lock=False))


def list_tasks(store, *, room_id, status=None):
    room_id = native._identifier(room_id, label="room_id")
    if status is not None and status not in native.TASK_STATUSES:
        raise native.DriverValidationError("invalid task status")
    with store.read() as conn:
        return [native._task_from_row(row) for row in repo.task_rows(conn, store, room_id, status)]


def get_task_for_turn(store, identity):
    with store.read() as conn:
        row = conn.execute(select(tasks).where(room_repo.scope(tasks, store, identity.room_id),
            tasks.c.thread_id == identity.thread_id, tasks.c.turn_id == identity.turn_id)).mappings().one_or_none()
        return native._task_from_row(room_repo.decode(row)) if row is not None else None
