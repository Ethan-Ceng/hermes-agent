"""Failure and lifecycle contracts preserve durable crypto instead of falling back."""

import asyncio
from contextlib import contextmanager
import threading
import pytest
from tests.hermes_db.matrix_support import new_store, current_engine, group_pair

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_cancelled_sdk_transaction_rolls_back_and_releases_connection(pg_profiles):
    from hermes_db.domains.plugin_storage.matrix.postgres.operations.accounts import put_next_batch
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        entered, release = threading.Event(), threading.Event()
        def held_write(conn, reference):
            put_next_batch(conn, reference, next_batch="cancelled")
            entered.set()
            assert release.wait(15)
        async def worker():
            async with store.transaction():
                await store.runtime.call(held_write, write=True)
        try:
            await store.put_next_batch("before")
            task = asyncio.create_task(worker())
            try:
                assert await asyncio.to_thread(entered.wait, 10)
                task.cancel()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await store.get_next_batch() == "before"
            assert current_engine().pool.checkedout() == 0
        finally:
            release.set()
            await store.close()


@pytest.mark.asyncio
async def test_unknown_commit_is_observable_without_retry_in_sdk_transaction(pg_profiles, monkeypatch):
    from hermes_db.domains.plugin_storage.matrix.postgres import runtime
    from hermes_db.errors import UnknownCommitError
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        original, writes = runtime.unit_of_work, []
        @contextmanager
        def lose_ack(reference, *, write=False):
            with original(reference, write=write) as conn:
                yield conn
            if write:
                writes.append(True)
                raise UnknownCommitError("injected confirmation loss after real crypto COMMIT")
        try:
            monkeypatch.setattr(runtime, "unit_of_work", lose_ack)
            with pytest.raises(UnknownCommitError):
                async with store.transaction():
                    await store.put_next_batch("actually committed")
                    await store.put_devices("@committed:matrix.test", {})
            assert writes == [True]
            monkeypatch.setattr(runtime, "unit_of_work", original)
            assert await store.get_next_batch() == "actually committed"
            assert await store.get_devices("@committed:matrix.test") == {}
            assert current_engine().pool.checkedout() == 0
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_identity_collision_wrong_pickle_and_retired_dataset_are_explicit(pg_profiles):
    from mautrix.crypto import OlmAccount
    from hermes_db.errors import StorageConflictError, StorageConfigurationError
    from hermes_db.domains.plugin_storage.matrix.api import unit_of_work
    from hermes_db.domains.plugin_storage.matrix.postgres.queries.crypto import scope
    from hermes_db.tables.matrix_crypto import roots
    from sqlalchemy import delete
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        await store.put_account(OlmAccount())
        try:
            with pytest.raises(StorageConflictError):
                await store.put_account(OlmAccount())
            wrong = new_store(pickle_key="wrong-key")
            await wrong.open()
            try:
                with pytest.raises(Exception, match="BAD_ACCOUNT_KEY"):
                    await wrong.get_account()
            finally:
                await wrong.close()
            with pytest.raises(StorageConfigurationError):
                await store.put_device_id("DIFFERENT")
            with unit_of_work(store.reference, write=True) as conn:
                conn.execute(delete(roots).where(scope(roots, store.reference)))
            with pytest.raises(StorageConfigurationError, match="dataset changed"):
                await store.get_account()
            fresh = new_store()
            await fresh.open()
            try:
                assert await fresh.get_account() is None
                with pytest.raises(StorageConfigurationError):
                    await store.put_next_batch("stale resurrection")
            finally:
                await fresh.close()
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_outbound_old_session_update_cannot_overwrite_rotated_group(pg_profiles):
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        try:
            old, _ = group_pair()
            new, _ = group_pair()
            await store.add_outbound_group_session(old)
            await store.add_outbound_group_session(new)
            old.encrypt("late old write")
            await store.update_outbound_group_session(old)
            current = await store.get_outbound_group_session(new.room_id)
            assert current.id == new.id and current.message_count == 0
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_captured_owner_survives_ambient_profile_and_rejects_store_change(pg_profiles):
    import hermes_yaml as yaml
    from hermes_cli.config import atomic_config_write
    from hermes_db.errors import StorageConfigurationError
    with pg_profiles("one") as home:
        store = new_store()
        await store.open()
        await store.put_next_batch("owning-profile")
        original = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    try:
        with pg_profiles("two"):
            assert await store.get_next_batch() == "owning-profile"
            changed = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
            changed["storage"]["postgresql"]["store_id"] = "replacement-owner"
            atomic_config_write(home / "config.yaml", changed)
            with pytest.raises(StorageConfigurationError, match="store_id changed"):
                await store.put_next_batch("must not retarget")
            atomic_config_write(home / "config.yaml", original)
            assert await store.get_next_batch() == "owning-profile"
    finally:
        atomic_config_write(home / "config.yaml", original)
        await store.close()
