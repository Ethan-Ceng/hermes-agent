"""Bind runtime components to one existing session resource; construction performs no I/O."""

def create_runtime_store(session_store):
    from hermes_db.domains.runtime.postgres.admissions import RuntimeAdmissions
    from hermes_db.domains.runtime.postgres.local import RuntimeLocal
    from hermes_db.domains.runtime.postgres.workers import RuntimeWorkers
    from hermes_db.domains.runtime.postgres.delegations import AsyncDelegationStore
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore

    context = OwnedRuntimeContext(session_store._context, session_store._lifecycle.collect_retired_media, create_worker_handlers)
    return PostgresRuntimeStore(context, RuntimeAdmissions(context), RuntimeLocal(context),
        OwnedRuntimePolicy(context), RuntimeWorkers(context), OwnedRuntimeMedia(context), AsyncDelegationStore(context))


def create_worker_handlers(home, operation):
    from hermes_db.domains.runtime.postgres.operations.worker_handlers import handlers
    from hermes_cli.observability.worker_metrics_bridge import prepare_policy, record
    policy = prepare_policy(home, operation)
    return handlers(metrics_policy=policy, record_engagement=record, automation_states=worker_automation_state_types)


def worker_automation_state_types():
    from hermes_cli.goals import GoalState
    from hermes_cli.heartbeat import HeartbeatState
    from hermes_cli.loops import LoopState
    return (("goal", GoalState), ("heartbeat", HeartbeatState), ("loop", LoopState))




from contextlib import contextmanager
from hermes_db.domains.runtime.postgres.context import RuntimeContext
from hermes_db.domains.runtime.postgres.media import RuntimeMedia
from hermes_db.domains.runtime.postgres.policy import RuntimePolicy


class OwnedRuntimeContext(RuntimeContext):
    @contextmanager
    def write(self):
        with self.session.profile.activate(), self.session.write() as conn:
            yield conn


class OwnedRuntimeMedia(RuntimeMedia):
    def release_media(self, references, *, retain_history=True):
        return self._context.session.effects.release_media(self._context.session, references, retain_history=retain_history)


class OwnedRuntimePolicy(RuntimePolicy):
    def mutate_session(self, **kwargs):
        result, event = self.mutate_session_data(**kwargs)
        if event is not None:
            self._context.session.effects.deleted(event[0], reason=event[1], primary=kwargs['session_id'])
            if event[1] == 'delete':
                self._context.collect_retired_media()
        return result
