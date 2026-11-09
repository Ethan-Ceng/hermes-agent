"""Bind runtime components to one existing session resource; construction performs no I/O."""

def create_runtime_store(session_store):
    from hermes_db.domains.runtime.postgres.context import RuntimeContext
    from hermes_db.domains.runtime.postgres.admissions import RuntimeAdmissions
    from hermes_db.domains.runtime.postgres.local import RuntimeLocal
    from hermes_db.domains.runtime.postgres.policy import RuntimePolicy
    from hermes_db.domains.runtime.postgres.workers import RuntimeWorkers
    from hermes_db.domains.runtime.postgres.media import RuntimeMedia
    from hermes_db.domains.runtime.postgres.delegations import AsyncDelegationStore
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore

    context = RuntimeContext(session_store._context, session_store._lifecycle.collect_retired_media)
    return PostgresRuntimeStore(context, RuntimeAdmissions(context), RuntimeLocal(context),
        RuntimePolicy(context), RuntimeWorkers(context), RuntimeMedia(context), AsyncDelegationStore(context))
