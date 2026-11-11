"""The SDK close protocol drains shielded driver work without starving release callbacks."""

import asyncio
import os
import signal
import threading
from types import SimpleNamespace

import pytest

from tests.waiting import async_wait_until


class _CloseDeadline(BaseException):
    pass


def _adapter():
    from mautrix.client.state_store import SyncStore
    from mautrix.crypto.store import CryptoStore
    from hermes_db.domains.plugin_storage.matrix.postgres.crypto import PostgresCryptoStore
    from hermes_cli.db_matrix_runtime import MatrixRuntime
    from plugins.platforms.matrix.adapter_storage import _StoreLifecycle

    # Only the close protocol is under test; no configuration, connection or SQL is substituted.
    store = object.__new__(PostgresCryptoStore)
    store._pid = os.getpid()
    store.runtime = MatrixRuntime(None, None)
    assert isinstance(store, (CryptoStore, SyncStore))
    return store, SimpleNamespace(_closing=False, _sync_task=None, _invite_join_tasks={},
        _reaction_redaction_tasks=set(), _crypto_db=_StoreLifecycle(store), _client=None)


@pytest.mark.asyncio
@pytest.mark.platforms('linux')
async def test_disconnect_drains_done_driver_before_its_release_callback():
    from plugins.platforms.matrix.adapter import MatrixAdapter

    store, adapter = _adapter()
    entered, release = threading.Event(), threading.Event()
    completed = asyncio.Event()

    def driver():
        entered.set()
        assert release.wait(timeout=8)

    async def operation():
        await asyncio.to_thread(driver)
        completed.set()

    caller = asyncio.create_task(store.runtime._wait(operation()))
    assert await asyncio.to_thread(entered.wait, 2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    adapter._sync_task = caller

    async def disconnect():
        await completed.wait()
        await MatrixAdapter.disconnect(adapter)

    closing = asyncio.create_task(disconnect())

    def deadline(signum, frame):
        raise _CloseDeadline('Matrix close starved a completed driver release callback')

    previous = signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, 3)
    try:
        release.set()
        await closing
        assert not store.runtime.pending
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        release.set()
        await asyncio.gather(caller, closing, *tuple(store.runtime.pending), return_exceptions=True)
        await store.close()


@pytest.mark.asyncio
@pytest.mark.platforms('linux')
async def test_cancelled_disconnect_keeps_live_driver_tracked_until_it_finishes():
    from plugins.platforms.matrix.adapter import MatrixAdapter

    store, adapter = _adapter()
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def driver():
        entered.set()
        try:
            assert release.wait(timeout=8)
        finally:
            exited.set()

    caller = asyncio.create_task(store.runtime._wait(asyncio.to_thread(driver)))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        adapter._sync_task = caller
        closing = asyncio.create_task(MatrixAdapter.disconnect(adapter))
        await async_wait_until(lambda: store.runtime.closed, timeout=2, what='Matrix disconnect entered')
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert store.runtime.pending and all(not task.cancelled() for task in store.runtime.pending)
        assert not exited.is_set()
        release.set()
        await MatrixAdapter.disconnect(adapter)
        assert exited.is_set() and not store.runtime.pending
    finally:
        release.set()
        assert await asyncio.to_thread(exited.wait, 2)
        await asyncio.gather(caller, *tuple(store.runtime.pending), return_exceptions=True)
        await store.close()
