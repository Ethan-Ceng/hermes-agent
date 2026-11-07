"""Trust/TOFU and signatures follow actual SDK transactions and owning device scopes."""

import asyncio
import pytest
from tests.hermes_db.matrix_support import new_store

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_devices_tofu_signatures_and_delete_survive_reopen(pg_profiles):
    from mautrix.types import DeviceIdentity, TrustState, CrossSigner, CrossSigningUsage
    from mautrix.crypto import OlmAccount
    from tests.hermes_db.matrix_support import group_pair
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        user = "@peer:matrix.test"
        device = DeviceIdentity(user, "PEER", "curve", "ed", TrustState.VERIFIED, False, "name\x00🙂")
        target, signer = CrossSigner(user, "target"), CrossSigner(user, "signer")
        _, inbound = group_pair()
        await store.put_group_session(inbound.room_id, inbound.sender_key, inbound.id, inbound)
        await store.put_account(OlmAccount())
        assert await store.get_devices(user) is None
        async with store.transaction():
            await store.put_devices(user, {device.device_id: device})
            await store.put_cross_signing_key(user, CrossSigningUsage.MASTER, "first")
            await store.put_signature(target, signer, "signature\x00🙂")
        await store.put_cross_signing_key(user, CrossSigningUsage.MASTER, "rotated")
        await store.put_devices("@tracked-empty:matrix.test", {})
        await store.flush()
        await store.close()
        store = new_store()
        await store.open()
        try:
            assert await store.get_devices(user) == {device.device_id: device}
            assert await store.find_device_by_key(user, "curve") == device
            assert await store.get_device(user, "PEER") == device
            assert await store.get_device(user, "unknown") is None
            assert await store.get_devices("@tracked-empty:matrix.test") == {}
            assert await store.filter_tracked_users([user, "unknown"]) == [user]
            keys = await store.get_cross_signing_keys(user)
            assert keys[CrossSigningUsage.MASTER].key == "rotated" and keys[CrossSigningUsage.MASTER].first == "first"
            assert await store.is_key_signed_by(target, signer)
            assert await store.drop_signatures_by_key(signer) == 1
            assert not await store.is_key_signed_by(target, signer)
            await store.delete()
            assert await store.get_account() is None and await store.get_device_id() is None
            assert await store.has_group_session(inbound.room_id, inbound.id)
            assert await store.get_device(user, "PEER") == device
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_transactions_rollback_savepoints_and_reject_child_inheritance(pg_profiles):
    from hermes_db.errors import StorageWriteError, StorageClosedError
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        try:
            await store.put_next_batch("before")
            with pytest.raises(ValueError, match="rollback"):
                async with store.transaction():
                    await store.put_next_batch("rolled back")
                    await store.put_devices("@rollback:matrix.test", {})
                    raise ValueError("rollback")
            assert await store.get_next_batch() == "before"
            assert await store.get_devices("@rollback:matrix.test") is None
            async with store.transaction():
                await store.put_next_batch("outer")
                with pytest.raises(ValueError):
                    async with store.transaction():
                        await store.put_next_batch("inner")
                        raise ValueError("savepoint")
                assert await store.get_next_batch() == "outer"
                with pytest.raises(StorageWriteError, match="child tasks"):
                    await asyncio.create_task(store.get_next_batch())
            assert await store.get_next_batch() == "outer"
        finally:
            await store.close()
        with pytest.raises(StorageClosedError):
            await store.get_next_batch()


@pytest.mark.asyncio
async def test_same_profile_accounts_devices_and_homeservers_are_isolated(pg_profiles):
    with pg_profiles("one"):
        owner = new_store()
        await owner.open()
        await owner.put_next_batch("owner")
        try:
            for override in (dict(device_id="OTHER"), dict(account_id="@other:matrix.test"), dict(homeserver="https://other.test")):
                other = new_store(**override)
                await other.open()
                try:
                    assert await other.get_next_batch() is None
                    await other.put_next_batch("other")
                finally:
                    await other.close()
            assert await owner.get_next_batch() == "owner"
        finally:
            await owner.close()
