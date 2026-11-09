"""Bridge async SDK calls to synchronous Core; an SDK transaction stays on one thread."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from contextvars import ContextVar, copy_context
import sys

from sqlalchemy.exc import DBAPIError, IntegrityError
from hermes_db.domains.plugin_storage.matrix.api import unit_of_work
from hermes_db.errors import RetryableStorageError, StorageBusyError, StorageClosedError, StorageConflictError, StorageWriteError


def _body_call(operation, conn, reference, arguments):
    try:
        return operation(conn, reference, **arguments)
    except IntegrityError:
        raise StorageConflictError("Matrix encryption constraint conflict") from None
    except DBAPIError as error:
        state = getattr(error.orig, "sqlstate", None)
        kind = {"40001": RetryableStorageError, "40P01": RetryableStorageError, "55P03": StorageBusyError}.get(state, StorageWriteError)
        raise kind("Matrix encryption transaction failed") from None


def _unit(reference, operation, write, arguments):
    with unit_of_work(reference, write=write) as conn:
        return operation(conn, reference, **arguments)


class _Transaction:
    def __init__(self, reference):
        self.reference = reference
        self.owner = asyncio.current_task()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matrix-core")
        self.context = copy_context()
        self.done = asyncio.Event()

    def submit(self, function, *args):
        return asyncio.wrap_future(self.pool.submit(self.context.run, function, *args))

    def begin(self):
        self.manager = unit_of_work(self.reference, write=True)
        self.conn = self.manager.__enter__()

    def end(self, exception):
        return self.manager.__exit__(*exception)


class MatrixRuntime:
    def __init__(self, reference):
        self.reference = reference
        self.closed = False
        self.pending = set()
        self.transactions = set()
        self.active = ContextVar("matrix_transaction", default=None)

    async def _wait(self, future):
        task = asyncio.ensure_future(future)
        self.pending.add(task)
        task.add_done_callback(self._finished)
        # Cancellation cannot terminate a synchronous driver call. Keep tracking it until close.
        return await asyncio.shield(task)

    def _finished(self, task):
        self.pending.discard(task)
        if not task.cancelled():
            task.exception()  # Observe failures even if its async caller was cancelled.

    def _actor(self):
        actor = self.active.get()
        if actor is not None and actor.owner is not asyncio.current_task():
            raise StorageWriteError("Matrix transactions cannot be inherited by child tasks")
        if self.closed and actor is None:
            raise StorageClosedError("Matrix encryption store is closed")
        return actor

    async def call(self, operation, *, write=False, **arguments):
        actor = self._actor()
        if actor is not None:
            return await self._wait(actor.submit(_body_call, operation, actor.conn, self.reference, arguments))
        return await self._wait(asyncio.to_thread(_unit, self.reference, operation, write, arguments))

    @asynccontextmanager
    async def transaction(self):
        actor = self._actor()
        if actor is not None:
            savepoint = await self._wait(actor.submit(actor.conn.begin_nested))
            try:
                yield
            except BaseException:
                await self._wait(actor.submit(savepoint.rollback))
                raise
            else:
                await self._wait(actor.submit(savepoint.commit))
            return
        actor = _Transaction(self.reference)
        self.transactions.add(actor)
        token = self.active.set(actor)
        try:
            # Beginning is shielded and must finish before exit is queued on this same worker.
            begin = actor.submit(actor.begin)
            try:
                await self._wait(begin)
            except asyncio.CancelledError:
                await asyncio.shield(begin)
                await self._wait(actor.submit(actor.end, sys.exc_info()))
                raise
            try:
                yield
            except BaseException:
                await self._wait(actor.submit(actor.end, sys.exc_info()))
                raise
            else:
                await self._wait(actor.submit(actor.end, (None, None, None)))
        finally:
            self.active.reset(token)
            # Drain cancelled calls before releasing the one-thread executor.
            await asyncio.shield(actor.submit(lambda: None))
            self.transactions.discard(actor)
            actor.done.set()
            actor.pool.shutdown(wait=False)

    async def close(self):
        if self.active.get() is not None:
            raise StorageWriteError("Close Matrix encryption store outside its transaction")
        self.closed = True
        await asyncio.gather(*(actor.done.wait() for actor in tuple(self.transactions)))
        while self.pending:
            # Yield to release callbacks even for done tasks; cancellation must retain live drivers.
            await asyncio.wait(tuple(self.pending))
