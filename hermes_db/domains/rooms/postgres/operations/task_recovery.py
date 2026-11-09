"""Current-owner reconciliation never automatically reexecutes uncertain work."""

from gateway import hosted_room_driver as native
from hermes_db.domains.rooms.postgres.operations.runs import change
from hermes_db.domains.rooms.postgres.operations.task_settlement import require_generations, settlement_fields


def _generation_change(store, identity, lease, execution, cancellation, *, status="indeterminate", now, fields,
                       message="indeterminate task generation changed", replay=None):
    def guard(row):
        require_generations(row, status, execution, cancellation, message)
    return change(store, identity, now=now, fields=fields, lease=lease, replay=replay, guard=guard)


def resolve_indeterminate_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation,
                               settlement_id, status, result, clock):
    native._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now, replay, params = native._settlement(settlement_id, status, result, clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation,
                              now=now, replay=replay, fields=settlement_fields(params))


def resolve_indeterminate_cancellation(store, identity, lease, *, expected_execution_generation,
                                      expected_cancel_generation, cancel_id, clock):
    native._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    cancel_id = native._identifier(cancel_id, label="cancel_id")
    now = native._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation,
        now=now, replay=native._cancel_replay(cancel_id), message="indeterminate cancellation proof is stale",
        fields=dict(status="cancelled", cancel_generation=expected_cancel_generation + 1,
                    cancel_id=cancel_id, terminal_at=now, updated_at=now))


def _queued(now, **extra):
    return dict(status="queued", run_gateway_id=None, run_process_generation=None, run_lease_generation=None,
                started_at=None, indeterminate_at=None, updated_at=now, **extra)


def requeue_indeterminate_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, clock):
    native._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = native._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation,
                              now=now, fields=_queued(now))


def defer_indeterminate_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, reason, clock):
    return _defer_task(store, identity, lease, expected_execution_generation, expected_cancel_generation,
                       reason, clock, status="indeterminate")


def defer_unconfirmed_stop(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, reason, clock):
    return _defer_task(store, identity, lease, expected_execution_generation, expected_cancel_generation,
                       reason, clock, status="stopping")


def _defer_task(store, identity, lease, execution, cancellation, reason, clock, *, status):
    native._expected_generations(lease, identity, execution, cancellation)
    reason = native._identifier(reason, label="defer_reason")
    encoded = native._canonical_json({"reason": reason, "retryable": True})
    now = native._timestamp(clock)
    def replay(row):
        deferred = native._generations_match(row, "deferred", execution, cancellation)
        return native._task_from_row(row, idempotent=True) if deferred and row["result_json"] == encoded else None
    return _generation_change(store, identity, lease, execution, cancellation, status=status,
        now=now, replay=replay, message=f"{status} task generation changed",
        fields=dict(status="deferred", result_json=encoded, terminal_at=now, updated_at=now))


def reopen_deferred_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, clock):
    native._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = native._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation,
        status="deferred", now=now, message="deferred task generation changed",
        fields=dict(status="indeterminate", result_json=None, terminal_at=None, started_at=now,
                    indeterminate_at=now, updated_at=now))


def requeue_deferred_task(store, identity, lease, *, expected_execution_generation, expected_cancel_generation, clock):
    native._expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = native._timestamp(clock)
    return _generation_change(store, identity, lease, expected_execution_generation, expected_cancel_generation,
        status="deferred", now=now, message="deferred task generation changed", fields=_queued(now, result_json=None, terminal_at=None))
