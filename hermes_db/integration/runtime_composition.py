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

    context = RuntimeContext(session_store._context, session_store._lifecycle.collect_retired_media, create_worker_handlers)
    return PostgresRuntimeStore(context, RuntimeAdmissions(context), RuntimeLocal(context),
        RuntimePolicy(context), RuntimeWorkers(context), RuntimeMedia(context), AsyncDelegationStore(context))


def create_worker_handlers(home, operation):
    from hermes_db.domains.runtime.postgres.operations.worker_handlers import handlers
    from hermes_db.integration.worker_metrics import prepare_policy, record
    policy = prepare_policy(home, operation)
    return handlers(metrics_policy=policy, record_engagement=record, automation_states=worker_automation_state_types)


def worker_automation_state_types():
    from hermes_cli.goals import GoalState
    from hermes_cli.heartbeat import HeartbeatState
    from hermes_cli.loops import LoopState
    return (("goal", GoalState), ("heartbeat", HeartbeatState), ("loop", LoopState))
