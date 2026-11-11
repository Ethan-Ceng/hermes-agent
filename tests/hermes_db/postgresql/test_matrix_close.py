"""The actual PG driver must finish its commit before the SDK close protocol releases it."""

import asyncio
import signal
import threading
from types import SimpleNamespace

import pytest

from tests.hermes_db.matrix_support import current_engine, new_store
from tests.waiting import async_wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms('linux')]


class _CloseDeadline(BaseException):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_close', [False, True])
async def test_sdk_disconnect_drains_cancelled_pg_write_and_preserves_its_commit(pg_profiles, cancel_close):
    from hermes_cli import db_matrix_runtime as matrix_runtime
    from hermes_db.domains.plugin_storage.matrix.postgres.operations.accounts import put_next_batch
    from plugins.platforms.matrix.adapter import MatrixAdapter
    from plugins.platforms.matrix.adapter_storage import _StoreLifecycle

    with pg_profiles('one'):
        store = new_store()
        await store.open()
        await store.put_next_batch('before-close')
        entered, release, driver_finished = threading.Event(), threading.Event(), threading.Event()
        committed = asyncio.Event()

        def write(conn, reference):
            put_next_batch(conn, reference, next_batch='committed-during-close')
            entered.set()
            assert release.wait(timeout=10)

        def driver():
            try:
                return matrix_runtime._unit(store.reference, write, True, {}, store.runtime.unit_of_work)
            finally:
                driver_finished.set()

        async def observed_operation():
            result = await asyncio.to_thread(driver)
            # Observe actual unit-of-work exit, after COMMIT, before its Task release callback.
            committed.set()
            return result

        caller = asyncio.create_task(store.runtime._wait(observed_operation()))
        adapter = SimpleNamespace(_closing=False, _sync_task=caller, _invite_join_tasks={},
            _reaction_redaction_tasks=set(), _crypto_db=_StoreLifecycle(store), _client=None)
        closing = None
        previous = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            if cancel_close:
                closing = asyncio.create_task(MatrixAdapter.disconnect(adapter))
                await async_wait_until(lambda: store.runtime.closed, timeout=2, what='PG crypto close entered')
                closing.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await closing
                assert store.runtime.pending and all(not task.cancelled() for task in store.runtime.pending)
                assert not driver_finished.is_set()

            async def disconnect_after_commit():
                nonlocal previous
                await asyncio.wait_for(committed.wait(), timeout=10)
                previous = signal.signal(signal.SIGALRM, deadline)
                signal.setitimer(signal.ITIMER_REAL, 5)
                await MatrixAdapter.disconnect(adapter)

            def deadline(signum, frame):
                raise _CloseDeadline('PG Matrix close starved its completed driver release callback')

            closing = asyncio.create_task(disconnect_after_commit())
            release.set()
            await closing
            assert driver_finished.is_set() and not store.runtime.pending
            assert current_engine().pool.checkedout() == 0
        finally:
            if previous is not None:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
            release.set()
            if closing is not None and not closing.done():
                closing.cancel()
            assert await asyncio.to_thread(driver_finished.wait, 10)
            await asyncio.gather(caller, *([closing] if closing else []), *tuple(store.runtime.pending),
                                 return_exceptions=True)
            await store.close()

        reopened = new_store()
        await reopened.open()
        try:
            assert await reopened.get_next_batch() == 'committed-during-close'
        finally:
            await reopened.close()
    with pg_profiles('two'):
        peer = new_store()
        await peer.open()
        try:
            assert await peer.get_next_batch() is None
        finally:
            await peer.close()
