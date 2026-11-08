"""Read actual session age from the selected Profile's scoped PG dataset."""

import time
from sqlalchemy import func, select
from hermes_db.factory import acquire_profile_domain
from hermes_db.tables.conversations import sessions


def first_session_started_at(profile_home):
    from agent.runtime_domain_store import worker_resource
    worker = worker_resource('metrics', profile_home=profile_home)
    if worker is not None:
        return worker.query('metrics.first_session', {})
    with acquire_profile_domain("sessions", profile_home=profile_home) as store, store.read() as conn:
        first = conn.scalar(select(func.min(sessions.c.started_at)).where(sessions.c.store_id == store.scope.require_store_id()))
    return time.time() if first is None else float(first)
