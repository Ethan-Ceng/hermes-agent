"""Profile-owned canonical runtime facade; ordinary session APIs stay separate."""

from contextlib import contextmanager

from sqlalchemy import select

from hermes_db.operations import runtime as operations
from hermes_db.operations import runtime_queue
from hermes_db.repositories import runtime as repo
from hermes_db.tables.runtime import session_admissions
from hermes_db.runtime_workers import RuntimeWorkers


class PostgresRuntimeStore(RuntimeWorkers):
    def __init__(self, session_store):
        self._store = session_store
        from hermes_db.delegation_store import AsyncDelegationStore
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
