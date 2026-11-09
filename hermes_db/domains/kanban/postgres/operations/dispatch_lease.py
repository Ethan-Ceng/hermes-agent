"""Durable, renewable dispatch ownership; no connection spans a filesystem or spawn wait."""

from contextlib import contextmanager
from threading import Event
import uuid

from sqlalchemy import BigInteger, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.core.resource import DomainResource
from hermes_db.errors import StorageBusyError, StorageError
from hermes_db.tables.kanban_dispatch import dispatch_leases as leases

LEASE_SECONDS = 60
RENEW_SECONDS = 10


def _now():
    return cast(func.extract("epoch", func.clock_timestamp()), BigInteger)


def _key(store):
    return leases.c.store_id == store.scope.require_store_id()


class DispatchLease:
    def __init__(self, store):
        self.store = store
        self.token = uuid.uuid4().hex
        self.stopping = Event()
        self.error = None

    def acquire(self):
        with DomainResource.write(self.store) as conn:
            statement = insert(leases).values(store_id=self.store.scope.require_store_id(), token=self.token,
                                               lease_until=_now() + LEASE_SECONDS)
            return conn.scalar(statement.on_conflict_do_update(index_elements=[leases.c.store_id],
                set_={"token": self.token, "lease_until": _now() + LEASE_SECONDS},
                where=leases.c.lease_until <= _now()).returning(leases.c.token)) == self.token

    def validate(self, conn, *, lock=False):
        if self.error is not None:
            raise self.error
        statement = select(leases.c.token).where(_key(self.store), leases.c.lease_until > _now())
        if lock:
            statement = statement.with_for_update()
        if conn.scalar(statement) != self.token:
            raise StorageBusyError("Kanban dispatch lease expired or was replaced; no new worker may start")

    def check(self):
        with self.store.read() as conn:
            self.validate(conn)

    def renew(self):
        with DomainResource.write(self.store) as conn:
            changed = conn.execute(update(leases).where(_key(self.store), leases.c.token == self.token,
                leases.c.lease_until > _now()).values(lease_until=_now() + LEASE_SECONDS)).rowcount
            if changed != 1:
                raise StorageBusyError("Kanban dispatch lease was lost during a tick")

    def _keep_alive(self):
        while not self.stopping.wait(RENEW_SECONDS):
            try:
                self.renew()
            except StorageError as error:
                self.error = error
                return

    def release(self):
        with DomainResource.write(self.store) as conn:
            conn.execute(delete(leases).where(_key(self.store), leases.c.token == self.token))


def _finish_tick(lease, thread):
    lease.stopping.set()
    # A renewal finishes its bounded short write before releasing ownership.
    thread.join()
    lease.release()


@contextmanager
def hold_dispatch_lease(store):
    from agent.memory_provider import spawn_context_thread
    lease = DispatchLease(store)
    if not lease.acquire():
        yield None
        return
    thread = spawn_context_thread(lease._keep_alive, name="kanban-dispatch-lease", daemon=True)
    thread.start()
    try:
        yield lease
    except BaseException as primary:
        try:
            _finish_tick(lease, thread)
        except StorageError as cleanup:
            primary.add_note(f"Dispatch lease release failed ({type(cleanup).__name__}); ownership expires by database time")
        raise
    else:
        _finish_tick(lease, thread)
