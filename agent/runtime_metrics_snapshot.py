"""Read actual session age from the selected Profile's scoped PG dataset."""

import time
from hermes_cli.db_domains import acquire_profile_domain


def first_session_started_at(profile_home):
    from agent.runtime_domain_store import worker_resource
    worker = worker_resource('metrics', profile_home=profile_home)
    if worker is not None:
        return worker.query('metrics.first_session', {})
    from hermes_db.domains.observations import first_session_started_at as query
    with acquire_profile_domain("sessions", profile_home=profile_home) as store, store.read() as conn:
        first = query(conn, store.scope.require_store_id())
    return time.time() if first is None else float(first)
