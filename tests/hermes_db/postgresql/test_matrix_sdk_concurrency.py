"""Independent reviewer diagnostic; no source/test-suite mutation."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_real_sdk_room_key_request_storage_error_reaches_cursor(pg_profiles, monkeypatch):
    from tests.hermes_db.postgresql.test_matrix_adapter_storage import adapter_client
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.domains.plugin_storage.matrix.postgres.operations import accounts as matrix_accounts
    with pg_profiles("one"):
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _remote):
            assert await adapter._connect_setup_e2ee(client, api, state)
            store = client.crypto.crypto_store
            await store.put_next_batch("before-real-key-request")
            calls = []
            def unavailable(*args, **kwargs):
                calls.append(True)
                raise StorageUnavailableError("review-injected key-request device read failure")
            monkeypatch.setattr(matrix_accounts, "get_device", unavailable)
            sync = {
                "next_batch": "after-lost-key-request",
                "device_one_time_keys_count": {"signed_curve25519": 50},
                "to_device": {"events": [{
                    "type": "m.room_key_request", "sender": "@bot:matrix.test",
                    "content": {
                        "action": "request", "request_id": "review-request", "requesting_device_id": "PEER",
                        "body": {"algorithm": "m.megolm.v1.aes-sha2", "room_id": "!review:matrix.test",
                            "sender_key": "sender", "session_id": "session"}}}]}}
            raised = False
            try:
                await adapter._absorb_sync(client, sync)
            except StorageUnavailableError:
                raised = True
            assert calls, "The actual SDK did not reach the injected PG read"
            cursor = await store.get_next_batch()
            print(f"REVIEW_EVIDENCE read_calls={len(calls)} raised={raised} cursor={cursor}")
            assert raised and cursor == "before-real-key-request"


@pytest.mark.asyncio
async def test_real_sdk_concurrent_to_device_sends_keep_olm_ratchet(pg_profiles, monkeypatch):
    import asyncio
    from tests.hermes_db.matrix_support import new_store, sdk_machine, olm_pair
    from mautrix.types import DeviceIdentity, TrustState, EventType, RoomKeyRequestEventContent, KeyRequestAction
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        alice, bob, outbound, inbound = olm_pair()
        await store.put_account(alice)
        await store.add_session(bob.identity_key, outbound)
        peer = DeviceIdentity("@peer:matrix.test", "PEER", bob.identity_key, bob.signing_key, TrustState.VERIFIED, False, "peer")
        original = store.get_latest_session
        loaded = []
        both = asyncio.Event()
        async def load_together(key):
            value = await original(key)
            loaded.append(value)
            if len(loaded) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 15)
            return value
        monkeypatch.setattr(store, "get_latest_session", load_together)
        sent, decoded, errors = [], [], []
        try:
            async with sdk_machine(store) as (machine, client):
                async def send(event_type, user_id, device_id, content):
                    sent.append(content.ciphertext[bob.identity_key])
                monkeypatch.setattr(client, "send_to_one_device", send)
                content = [RoomKeyRequestEventContent(action=KeyRequestAction.CANCEL, request_id=str(number), requesting_device_id="DEVICE") for number in range(2)]
                await asyncio.gather(*(machine.send_encrypted_to_device(peer, EventType.ROOM_KEY_REQUEST, body) for body in content))
                for message in sent:
                    try:
                        decoded.append(inbound.decrypt(message))
                    except Exception as error:
                        errors.append(type(error).__name__ + ": " + str(error))
                print(f"REVIEW_RATCHET sent={len(sent)} decoded={len(decoded)} errors={errors} same_session_object={loaded[0] is loaded[1]}")
                assert len(decoded) == 2 and not errors
        finally:
            await store.close()
