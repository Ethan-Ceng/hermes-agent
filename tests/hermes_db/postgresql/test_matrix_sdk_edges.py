"""Independent follow-up diagnostics using real SDK and ownership-checked PG."""

import asyncio
from contextlib import contextmanager
import json

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_pg_sync_failure_requests_supervised_reconnect_and_keeps_cursor(pg_profiles, monkeypatch):
    from tests.hermes_db.postgresql.test_matrix_adapter_storage import adapter_client
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.domains.plugin_storage.matrix.postgres.operations import accounts as matrix_accounts
    with pg_profiles("one"):
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _remote):
            assert await adapter._connect_setup_e2ee(client, api, state)
            store = client.crypto.crypto_store
            await store.put_next_batch("before-reconnect")
            original = matrix_accounts.get_device
            calls, notifications = [], []
            def unavailable(*args, **kwargs):
                calls.append(True)
                raise StorageUnavailableError("isolated PG interruption")
            async def sync(**kwargs):
                assert kwargs["since"] == "before-reconnect"
                return {"next_batch": "must-not-advance", "device_one_time_keys_count": {"signed_curve25519": 50},
                    "to_device": {"events": [request_event()]}}
            async def reconnect(failed):
                notifications.append(failed)
            adapter.set_fatal_error_handler(reconnect)
            monkeypatch.setattr(matrix_accounts, "get_device", unavailable)
            monkeypatch.setattr(client, "sync", sync)
            await asyncio.wait_for(adapter._sync_loop(), 20)
            assert calls and notifications == [adapter]
            assert adapter.has_fatal_error and adapter.fatal_error_retryable and not adapter._running
            assert await store.get_next_batch() == "before-reconnect"
            monkeypatch.setattr(matrix_accounts, "get_device", original)
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _remote):
            assert await adapter._connect_setup_e2ee(client, api, state)
            store = client.crypto.crypto_store
            assert await store.get_next_batch() == "before-reconnect"
            assert await adapter._absorb_sync(client, {"next_batch": "reconnected", "to_device": {"events": []},
                "device_one_time_keys_count": {"signed_curve25519": 50}}) == "reconnected"
            assert await store.get_next_batch() == "reconnected"


def request_event(sender="@bot:matrix.test"):
    return {"type": "m.room_key_request", "sender": sender, "content": {
        "action": "request", "request_id": "edge-request", "requesting_device_id": "PEER",
        "body": {"algorithm": "m.megolm.v1.aes-sha2", "room_id": "!edge:matrix.test",
            "sender_key": "sender", "session_id": "session"}}}


@pytest.mark.asyncio
async def test_real_sdk_swallowed_transaction_confirmation_loss_blocks_cursor(pg_profiles, monkeypatch):
    from tests.hermes_db.postgresql.test_matrix_adapter_storage import adapter_client
    from hermes_db.errors import UnknownCommitError
    from hermes_cli import db_matrix_runtime as runtime
    from mautrix.crypto import OlmAccount
    from mautrix.types import QueryKeysResponse
    with pg_profiles("one"):
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _remote):
            assert await adapter._connect_setup_e2ee(client, api, state)
            store = client.crypto.crypto_store
            await store.put_next_batch("before-sdk-transaction")
            peer = OlmAccount().get_device_keys(str(client.mxid), "PEER")
            async def query(*args, **kwargs):
                return QueryKeysResponse.deserialize({"device_keys": {str(client.mxid): {"PEER": peer.serialize()}}, "failures": {}})
            monkeypatch.setattr(client, "query_keys", query)
            original, committed = store.runtime.unit_of_work, []
            @contextmanager
            def lose_first_write_ack(reference, *, write=False):
                with original(reference, write=write) as conn:
                    yield conn
                if write and not committed:
                    committed.append(True)
                    raise UnknownCommitError("review loss after actual SDK device transaction COMMIT")
            monkeypatch.setattr(store.runtime, "unit_of_work", lose_first_write_ack)
            raised = False
            try:
                await adapter._absorb_sync(client, {"next_batch": "after-sdk-transaction", "device_one_time_keys_count": {"signed_curve25519": 50},
                    "to_device": {"events": [request_event()]}})
            except UnknownCommitError:
                raised = True
            monkeypatch.setattr(store.runtime, "unit_of_work", original)
            assert committed and await store.get_device(str(client.mxid), "PEER") is not None
            cursor = await store.get_next_batch()
            print(f"REVIEW_TRANSACTION raised={raised} cursor={cursor} committed_device=True")
            assert raised and cursor == "before-sdk-transaction"


@pytest.mark.asyncio
async def test_real_encrypted_to_device_descendant_storage_error_blocks_cursor(pg_profiles, monkeypatch):
    from tests.hermes_db.postgresql.test_matrix_adapter_storage import adapter_client
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.domains.plugin_storage.matrix.postgres.operations import accounts as matrix_accounts
    from mautrix.crypto import OlmAccount
    with pg_profiles("one"):
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _remote):
            assert await adapter._connect_setup_e2ee(client, api, state)
            store, bot = client.crypto.crypto_store, client.crypto.account
            await store.put_next_batch("before-encrypted-descendant")
            bot.generate_one_time_keys(1)
            await store.put_account(bot)
            peer = OlmAccount()
            sender = "@peer:matrix.test"
            payload = dict(request_event(sender), sender_device="PEER", keys={"ed25519": peer.signing_key},
                recipient=str(client.mxid), recipient_keys={"ed25519": bot.signing_key})
            outgoing = peer.new_outbound_session(bot.identity_key, next(iter(bot.one_time_keys["curve25519"].values())))
            message = outgoing.encrypt(json.dumps(payload))
            arrived = asyncio.Event()
            def unavailable(*args, **kwargs):
                asyncio_loop.call_soon_threadsafe(arrived.set)
                raise StorageUnavailableError("review descendant device storage read failed")
            asyncio_loop = asyncio.get_running_loop()
            monkeypatch.setattr(matrix_accounts, "get_device", unavailable)
            raised = False
            try:
                await adapter._absorb_sync(client, {"next_batch": "after-encrypted-descendant", "device_one_time_keys_count": {"signed_curve25519": 50},
                    "to_device": {"events": [{"type": "m.room.encrypted", "sender": sender, "content": {
                        "algorithm": "m.olm.v1.curve25519-aes-sha2", "sender_key": peer.identity_key,
                        "ciphertext": {bot.identity_key: message.serialize()}}}]}})
            except StorageUnavailableError:
                raised = True
            await asyncio.wait_for(arrived.wait(), 15)
            # Drain already scheduled SDK child handlers before fixture teardown.
            await asyncio.sleep(0)
            cursor = await store.get_next_batch()
            print(f"REVIEW_DESCENDANT raised={raised} cursor={cursor}")
            assert raised and cursor == "before-encrypted-descendant"


@pytest.mark.asyncio
async def test_cancelled_olm_save_waiting_for_gate_rejects_mutated_cached_ratchet(pg_profiles, monkeypatch):
    from tests.hermes_db.matrix_support import new_store, olm_pair, sdk_machine
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        alice, bob, outbound, inbound = olm_pair()
        await store.put_account(bob)
        await store.add_session(alice.identity_key, inbound)
        message = outbound.encrypt("cancel-before-save-gate")
        ready, proceed = asyncio.Event(), asyncio.Event()
        original = store.update_session
        async def pause_before_save(key, value):
            ready.set()
            await proceed.wait()
            return await original(key, value)
        monkeypatch.setattr(store, "update_session", pause_before_save)
        try:
            async with sdk_machine(store) as (machine, _client):
                async def no_unwedge(*args, **kwargs):
                    return None
                monkeypatch.setattr(machine, "_unwedge_session", no_unwedge)
                task = asyncio.create_task(machine._decrypt_olm_ciphertext("@peer:matrix.test", alice.identity_key, message))
                await asyncio.wait_for(ready.wait(), 15)
                async with store._olm_sessions.guard():
                    proceed.set()
                    await asyncio.sleep(0)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                poisoned = store._olm_sessions.failed
                retry_error = None
                try:
                    await machine._decrypt_olm_ciphertext("@peer:matrix.test", alice.identity_key, message)
                except Exception as error:
                    retry_error = type(error).__name__
                print(f"REVIEW_CANCEL_GATE poisoned={poisoned} retry_error={retry_error}")
                assert poisoned
            await store.close()
            store = new_store()
            await store.open()
            async with sdk_machine(store) as (machine, _client):
                assert await machine._decrypt_olm_ciphertext("@peer:matrix.test", alice.identity_key, message) == "cancel-before-save-gate"
            print("REVIEW_CANCEL_REOPEN replay=True")
        finally:
            proceed.set()
            await store.close()


@pytest.mark.asyncio
async def test_real_sdk_group_share_and_to_device_send_reopen_same_ratchet(pg_profiles, monkeypatch):
    from tests.hermes_db.matrix_support import new_store, olm_pair, sdk_machine, current_engine
    from mautrix.types import DeviceIdentity, TrustState, EventType, RoomKeyRequestEventContent, KeyRequestAction, RoomEncryptionStateEventContent, EncryptionAlgorithm
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        alice, bob, outbound, inbound = olm_pair()
        await store.put_account(alice)
        await store.add_session(bob.identity_key, outbound)
        peer = DeviceIdentity("@peer:matrix.test", "PEER", bob.identity_key, bob.signing_key, TrustState.VERIFIED, False, "peer")
        await store.put_devices(peer.user_id, {peer.device_id: peer})
        read, both = [], asyncio.Event()
        original = store.get_latest_session
        async def align(key):
            value = await original(key)
            read.append(value)
            if len(read) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 15)
            return value
        monkeypatch.setattr(store, "get_latest_session", align)
        body = RoomKeyRequestEventContent(action=KeyRequestAction.CANCEL, request_id="normal", requesting_device_id="DEVICE")
        sent = []
        try:
            async with sdk_machine(store) as (machine, client):
                async def encryption(*args, **kwargs):
                    assert store.runtime.active.get() is None
                    assert store._olm_sessions.owner is not asyncio.current_task()
                    return RoomEncryptionStateEventContent(algorithm=EncryptionAlgorithm.MEGOLM_V1)
                async def send_one(event_type, user_id, device_id, content):
                    assert store.runtime.active.get() is None
                    assert store._olm_sessions.owner is not asyncio.current_task()
                    sent.append(content.ciphertext[bob.identity_key])
                async def send_many(event_type, content):
                    assert store.runtime.active.get() is None
                    assert store._olm_sessions.owner is not asyncio.current_task()
                    sent.append(content[peer.user_id][peer.device_id].ciphertext[bob.identity_key])
                monkeypatch.setattr(client, "get_state_event", encryption)
                monkeypatch.setattr(client, "send_to_one_device", send_one)
                monkeypatch.setattr(client, "send_to_device", send_many)
                await asyncio.gather(machine.share_group_session("!group:matrix.test", [peer.user_id]),
                    machine.send_encrypted_to_device(peer, EventType.ROOM_KEY_REQUEST, body))
                assert current_engine().pool.checkedout() == 0
                assert len(sent) == 2 and read[0] is read[1]
                assert {json.loads(inbound.decrypt(value))["type"] for value in sent} == {"m.room_key", "m.room_key_request"}
            await store.close()
            store = new_store()
            await store.open()
            async with sdk_machine(store) as (machine, client):
                async def send_after(event_type, user_id, device_id, content):
                    assert current_engine().pool.checkedout() == 0
                    plain = json.loads(inbound.decrypt(content.ciphertext[bob.identity_key]))
                    assert plain["type"] == "m.room_key_request"
                monkeypatch.setattr(client, "send_to_one_device", send_after)
                await machine.send_encrypted_to_device(peer, EventType.ROOM_KEY_REQUEST, body)
            print("REVIEW_GROUP_SEND_REOPEN ok=True")
        finally:
            await store.close()
