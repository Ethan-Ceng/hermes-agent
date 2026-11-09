"""Exact task/lease fences for completion, Stop and proven non-admission."""

from gateway import hosted_room_driver as native
from hermes_db.domains.rooms.postgres.operations.runs import change


def settlement_fields(params):
    return dict(zip(("status", "settlement_id", "settlement_status", "result_json", "terminal_at", "updated_at"), params))


def require_generations(row, status, execution, cancellation, message):
    if not native._generations_match(row, status, execution, cancellation):
        raise native.StaleTaskError(message)


def run_guard(attempt, message):
    def guard(row):
        require_generations(row, "running", attempt.execution_generation, attempt.cancel_generation, message)
        if (row["run_gateway_id"], row["run_process_generation"], row["run_lease_generation"]) != native._run_fence(attempt.lease):
            raise native.StaleTaskError(message)
    return guard


def settle_task(store, attempt, *, settlement_id, status, result, clock):
    now, replay, params = native._settlement(settlement_id, status, result, clock)
    return change(store, attempt.identity, now=now, fields=settlement_fields(params),
        lease=attempt.lease, lease_first=False, replay=replay,
        guard=run_guard(attempt, "task attempt is stale or cancelled"))


def settle_stopping_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation,
                         settlement_id, status, result, clock):
    native._terminal_settlement_id(settlement_id, status)
    if expected_execution_generation < 1 or expected_cancel_generation < 1:
        raise native.DriverValidationError("stopping settlement generations are invalid")
    now, replay, params = native._settlement(settlement_id, status, result, clock)
    def guard(row):
        require_generations(row, "stopping", expected_execution_generation, expected_cancel_generation,
                            "task completion lost the stop race")
    return change(store, identity, now=now, fields=settlement_fields(params), lease=lease,
                  lease_first=False, replay=replay, guard=guard)


def requeue_not_admitted_task(store, attempt, *, clock):
    now = native._timestamp(clock)
    native._check_same_room(attempt.lease, attempt.identity)
    def replay(row):
        queued = native._generations_match(row, "queued", attempt.execution_generation, attempt.cancel_generation)
        cleared = (row["run_gateway_id"], row["run_process_generation"], row["run_lease_generation"]) == (None, None, None)
        return native._task_from_row(row, idempotent=True) if queued and cleared else None
    return change(store, attempt.identity, now=now, lease=attempt.lease, replay=replay,
        guard=run_guard(attempt, "not-admitted task attempt lost its fence"),
        fields=dict(status="queued", run_gateway_id=None, run_process_generation=None,
                    run_lease_generation=None, started_at=None, updated_at=now))


def _cancel_input(cancel_id, expected_cancel_generation, clock):
    cancel_id = native._identifier(cancel_id, label="cancel_id")
    native._cancel_generation(expected_cancel_generation)
    return cancel_id, native._timestamp(clock)


def cancel_task(store, identity, *, cancel_id, expected_cancel_generation, clock):
    cancel_id, now = _cancel_input(cancel_id, expected_cancel_generation, clock)
    def guard(row):
        if row["status"] in native.TERMINAL_STATUSES:
            raise native.InvalidTaskTransitionError(f"cannot cancel task in state '{row['status']}'")
        if row["status"] not in {"queued", "deferred"}:
            raise native.InvalidTaskTransitionError("running work requires acknowledged two-phase cancellation")
        native._require_cancel_generation(row, expected_cancel_generation)
    return change(store, identity, now=now, replay=native._cancel_replay(cancel_id), guard=guard,
        fields=dict(status="cancelled", cancel_generation=expected_cancel_generation + 1,
                    cancel_id=cancel_id, terminal_at=now, updated_at=now))


def begin_task_cancel(store, identity, *, cancel_id, expected_cancel_generation, clock):
    cancel_id, now = _cancel_input(cancel_id, expected_cancel_generation, clock)
    def guard(row):
        if row["status"] in native.TERMINAL_STATUSES or row["status"] == "queued":
            raise native.InvalidTaskTransitionError(f"cannot request remote stop in state '{row['status']}'")
        native._require_cancel_generation(row, expected_cancel_generation)
        if row["status"] not in {"running", "indeterminate"}:
            raise native.StaleTaskError("task changed during stop request")
    return change(store, identity, now=now, replay=native._cancel_replay(cancel_id, "stopping"), guard=guard,
        fields=dict(status="stopping", cancel_generation=expected_cancel_generation + 1, cancel_id=cancel_id, updated_at=now))


def complete_task_cancel(store, identity, *, cancel_id, expected_cancel_generation, clock):
    cancel_id = native._identifier(cancel_id, label="cancel_id")
    now = native._timestamp(clock)
    def guard(row):
        if (row["status"], row["cancel_id"], int(row["cancel_generation"])) != ("stopping", cancel_id, expected_cancel_generation):
            raise native.StaleTaskError("task stop acknowledgement is stale")
    return change(store, identity, now=now, replay=native._cancel_replay(cancel_id), guard=guard,
                  fields=dict(status="cancelled", terminal_at=now, updated_at=now))
