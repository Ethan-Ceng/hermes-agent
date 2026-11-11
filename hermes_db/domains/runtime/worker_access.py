"""Owner-side worker claim reads dispatch without exposing database details to compute."""

from hermes_db.health import is_postgresql_store
from hermes_db.domains.runtime.access import runtime_for_store


def worker_claim_origin(db, params):
    if is_postgresql_store(db):
        return runtime_for_store(db).worker_claim_origin(params)
    from hermes_state_worker_compression import worker_claim_origin as sqlite_origin
    return sqlite_origin(db, params)


def worker_retry_target(db, params):
    if is_postgresql_store(db):
        return runtime_for_store(db).worker_retry_target(params)
    from hermes_state_worker_compression import worker_retry_target as sqlite_target
    return sqlite_target(db, params)
