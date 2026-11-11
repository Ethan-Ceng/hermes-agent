"""Existing owner authorization, before database access where required."""

def verify_worker_delegation_owner(execution_id, worker_pid, worker_birth):
    """Capture process proof before acquiring any database connection or lock."""
    from hermes_db.domains.runtime.values import (
        VerifiedDelegationOwner, RuntimeStoreError, delegation_text as _text, delegation_number as _number,
    )
    import psutil
    from hermes_cli import process_identity
    from gateway.status import get_process_start_time
    _text(execution_id)
    if type(worker_pid) is not int or worker_pid <= 0:
        raise RuntimeStoreError("invalid_params")
    _number(worker_birth)
    try:
        if process_identity.worker_birth(psutil.Process(worker_pid)) != worker_birth:
            raise RuntimeStoreError("permission_denied")
        started_at = get_process_start_time(worker_pid)
    except psutil.Error:
        raise RuntimeStoreError("worker_not_live") from None
    return VerifiedDelegationOwner(execution_id, worker_pid, worker_birth, started_at)
