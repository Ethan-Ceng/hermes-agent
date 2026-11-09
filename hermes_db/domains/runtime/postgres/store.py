"""Profile-owned canonical runtime facade; ordinary session APIs stay separate."""

from contextlib import contextmanager

from sqlalchemy import select

from hermes_db.domains.runtime.postgres.operations import runtime as operations
from hermes_db.domains.runtime.postgres.operations import runtime_queue
from hermes_db.domains.runtime.postgres.queries import runtime as repo
from hermes_db.tables.runtime import session_admissions
from hermes_db.domains.runtime.postgres.capabilities.runtime_workers import RuntimeWorkers
from hermes_db.domains.runtime.postgres.capabilities.runtime_terminal import RuntimeTerminal
from hermes_db.domains.runtime.postgres.capabilities.runtime_local import RuntimeLocal
from hermes_db.domains.runtime.postgres.capabilities.runtime_history import RuntimeHistory
from hermes_db.domains.runtime.postgres.capabilities.runtime_api import RuntimeApi
from hermes_db.domains.runtime.postgres.capabilities.runtime_media import RuntimeMedia
from hermes_db.domains.runtime.postgres.capabilities.runtime_viewer import RuntimeViewer
from hermes_db.domains.runtime.postgres.capabilities.runtime_policy import RuntimePolicy
from hermes_db.domains.runtime.postgres.capabilities.runtime_bot import RuntimeBot
from hermes_db.domains.runtime.postgres.capabilities.runtime_recovery import RuntimeRecovery


class PostgresRuntimeStore(RuntimeWorkers, RuntimeTerminal, RuntimeLocal, RuntimeHistory, RuntimeApi, RuntimeMedia, RuntimeViewer, RuntimePolicy, RuntimeBot, RuntimeRecovery):
    def __init__(self, session_store):
        self._store = session_store
        from hermes_db.domains.runtime.postgres.delegations import AsyncDelegationStore
        self._delegations = AsyncDelegationStore(session_store)

    @property
    def scope(self):
        return self._store.scope

    @property
    def delegations(self):
        self._store._assert_open()
        return self._delegations

    @contextmanager
    def _write(self):
        with self._store._profile.activate(), self._store._write() as conn:
            yield conn

    def begin_epoch(self, *, instance_id):
        with self._write() as conn:
            return operations.begin_epoch(conn, self.scope, instance_id)

    def check_epoch(self, epoch):
        with self._store._read() as conn:
            repo.require_epoch(conn, self.scope, epoch)

    def current_epoch(self):
        from sqlalchemy import select
        from hermes_db.tables.runtime import runtime_epoch
        with self._store._read() as conn:
            return conn.scalar(select(runtime_epoch.c.epoch).where(runtime_epoch.c.store_id == self.scope.require_store_id(),
                runtime_epoch.c.singleton == 1))

    def mutate_session(self, **kwargs):
        from hermes_db.domains.sessions.postgres.operations.mutations import mutate
        with self._write() as conn:
            result, event = mutate(conn, self.scope, **kwargs)
        if event is not None:
            from hermes_db.integration.events import emit_deleted
            emit_deleted(self._store._profile, event[0], reason=event[1], primary=kwargs["session_id"])
            if event[1] == "delete":
                self._store.collect_retired_media()
        return result

    def policy_picks(self, session_id):
        from hermes_db.domains.sessions.postgres.operations.mutation_policy import picks
        with self._store._read() as conn:
            return picks(conn, self.scope, session_id)

    def commit_refreshed_policy(self, **kwargs):
        from hermes_db.domains.sessions.postgres.operations.mutation_policy import refresh
        with self._write() as conn:
            return refresh(conn, self.scope, **kwargs)

    def prepare_chat_pick(self, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.chat_pick import prepare
        with self._store._read() as conn:
            return prepare(conn, self.scope, **kwargs)

    def commit_chat_pick(self, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.chat_pick import commit
        with self._write() as conn:
            return commit(conn, self.scope, **kwargs)

    def admit_input(self, **kwargs):
        with self._write() as conn:
            return operations.admit(conn, self.scope, **kwargs)

    def claim_input(self, **kwargs):
        with self._write() as conn:
            return operations.claim(conn, self.scope, **kwargs)

    def settle_input(self, **kwargs):
        with self._write() as conn:
            return operations.settle(conn, self.scope, **kwargs)

    def cancel_input(self, **kwargs):
        with self._write() as conn:
            return operations.cancel(conn, self.scope, **kwargs)

    def steer_input(self, **kwargs):
        with self._write() as conn:
            return operations.steer(conn, self.scope, **kwargs)

    def revert_steer(self, **kwargs):
        with self._write() as conn:
            return operations.revert_steer(conn, self.scope, **kwargs)

    def recover_inputs(self, **kwargs):
        with self._write() as conn:
            return operations.recover(conn, self.scope, **kwargs)

    def resolve_unknown(self, **kwargs):
        with self._write() as conn:
            return operations.resolve_unknown(conn, self.scope, **kwargs)

    def mark_unknown(self, **kwargs):
        with self._write() as conn:
            return operations.mark_unknown(conn, self.scope, **kwargs)

    def rehome_inputs(self, **kwargs):
        with self._write() as conn:
            return runtime_queue.rehome(conn, self.scope, **kwargs)

    def retarget_automation(self, **kwargs):
        with self._write() as conn:
            return runtime_queue.retarget(conn, self.scope, **kwargs)

    def get_admission(self, *, admission_id):
        with self._store._read() as conn:
            return repo.public_row(repo.admission(conn, self.scope, admission_id))

    def find_admission(self, *, principal_id, session_id, request_id):
        with self._store._read() as conn:
            return repo.public_row(repo.find(conn, self.scope, principal_id, session_id, request_id))

    def list_admissions(self, *, session_id, pending_only=True):
        with self._store._read() as conn:
            conditions = [session_admissions.c.status.in_(("queued", "started", "unknown"))] if pending_only else []
            rows = conn.execute(select(session_admissions).where(repo.target_where(self.scope, session_id), *conditions)
                                .order_by(session_admissions.c.seq)).mappings()
            return [repo.public_row(row) for row in rows]
