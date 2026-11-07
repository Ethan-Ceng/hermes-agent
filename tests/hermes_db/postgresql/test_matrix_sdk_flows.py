"""Real OlmMachine consumers exercise device validation, key requests and encrypted events."""

import asyncio
import json
import pytest
from tests.hermes_db.matrix_support import new_store, sdk_machine, current_engine, group_pair

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_sdk_signed_device_query_uses_real_transaction_without_network_connection(pg_profiles, monkeypatch):
    from mautrix.crypto import OlmAccount
    from mautrix.types import QueryKeysResponse, CrossSigner
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        engine = current_engine()
        peer = OlmAccount()
        user, device = "@peer:matrix.test", "PEER"
        keys = peer.get_device_keys(user, device)
        calls = []
        async def query(*args, **kwargs):
            assert engine.pool.checkedout() == 0
            calls.append(True)
            return QueryKeysResponse.deserialize({"device_keys": {user: {device: keys.serialize()}}, "failures": {}})
        try:
            async with sdk_machine(store) as (machine, client):
                monkeypatch.setattr(client, "query_keys", query)
                fetched = await machine._fetch_keys([user], include_untracked=True)
                assert fetched[user][device].identity_key == peer.identity_key
                assert fetched[user][device].signing_key == peer.signing_key
                signer = CrossSigner(user, peer.signing_key)
                assert await store.is_key_signed_by(signer, signer)
                assert await store.filter_tracked_users([user]) == [user]
            assert calls and engine.pool.checkedout() == 0
        finally:
            await store.close()
        store = new_store()
        await store.open()
        try:
            assert (await store.get_device(user, device)).identity_key == peer.identity_key
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_sdk_key_request_forwarded_key_and_decrypt_reopen(pg_profiles, monkeypatch):
    from mautrix.types import DecryptedOlmEvent, EncryptedEvent, DeviceIdentity, TrustState, KeyRequestAction, RoomEncryptionStateEventContent
    from mautrix.errors import DuplicateMessageIndex
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        engine = current_engine()
        outbound, inbound = group_pair()
        user, device = "@peer:matrix.test", "PEER"
        await store.put_devices(user, {device: DeviceIdentity(user, device, inbound.sender_key, inbound.signing_key, TrustState.VERIFIED, False, "peer")})
        requested = asyncio.Event()
        sends, state_queries = [], []
        async def send(event_type, messages):
            assert engine.pool.checkedout() == 0
            sends.append(messages)
            requested.set()
        async def encryption_info(*args, **kwargs):
            assert engine.pool.checkedout() == 0
            state_queries.append(True)
            return RoomEncryptionStateEventContent()
        try:
            async with sdk_machine(store) as (machine, client):
                monkeypatch.setattr(client, "send_to_device", send)
                monkeypatch.setattr(client, "get_state_event", encryption_info)
                # 0.21.1 completion mutates this mapping by device id despite its list annotation.
                targets = {user: {device: None, "REMAINING": None}}
                request = asyncio.create_task(machine.request_room_key(inbound.room_id, inbound.sender_key, inbound.id, targets, timeout=15))
                await asyncio.wait_for(requested.wait(), 10)
                event = DecryptedOlmEvent.deserialize({"type": "m.forwarded_room_key", "sender": user,
                    "sender_device": device, "keys": {"ed25519": inbound.signing_key}, "recipient": store.account_id,
                    "recipient_keys": {"ed25519": machine.account.signing_key}, "content": {
                        "algorithm": "m.megolm.v1.aes-sha2", "room_id": inbound.room_id, "session_id": inbound.id,
                        "session_key": inbound.export_session(0), "sender_key": inbound.sender_key,
                        "sender_claimed_ed25519_key": inbound.signing_key, "forwarding_curve25519_key_chain": []}})
                event.sender_key = inbound.sender_key
                await machine._receive_forwarded_room_key(event)
                assert await request
                assert sends[0][user][device].action == KeyRequestAction.REQUEST
                assert sends[1][user]["REMAINING"].action == KeyRequestAction.CANCEL
                assert state_queries
            cipher = outbound.encrypt(json.dumps({"room_id": inbound.room_id, "type": "m.room.message", "content": {"msgtype": "m.text", "body": "SDK forwarded decrypt 🙂"}}))
            await store.close()
            store = new_store()
            await store.open()
            async with sdk_machine(store) as (machine, _):
                encrypted = EncryptedEvent.deserialize({"type": "m.room.encrypted", "room_id": inbound.room_id, "event_id": "$one", "sender": user,
                    "origin_server_ts": 123456, "content": {"algorithm": "m.megolm.v1.aes-sha2", "sender_key": inbound.sender_key,
                        "device_id": device, "session_id": inbound.id, "ciphertext": cipher}})
                plain = await machine.decrypt_megolm_event(encrypted)
                assert plain.content.body == "SDK forwarded decrypt 🙂"
                encrypted.event_id = "$replay"
                with pytest.raises(DuplicateMessageIndex):
                    await machine.decrypt_megolm_event(encrypted)
                loaded = await store.get_group_session(inbound.room_id, inbound.id)
                assert loaded.ratchet_safety.next_index == 1
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_sdk_outbound_encrypt_uses_persisted_group_after_restart(pg_profiles):
    from mautrix.crypto import InboundGroupSession, OutboundGroupSession
    from mautrix.types import EventType
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        try:
            async with sdk_machine(store) as (machine, _):
                outbound = OutboundGroupSession("!room:matrix.test")
                outbound.shared = True
                inbound = InboundGroupSession(outbound.session_key, machine.account.signing_key, machine.account.identity_key, outbound.room_id)
                await store.add_outbound_group_session(outbound)
            await store.close()
            store = new_store()
            await store.open()
            async with sdk_machine(store) as (machine, _):
                content = await machine.encrypt_megolm_event(outbound.room_id, EventType.ROOM_MESSAGE, {"body": "SDK outbound", "msgtype": "m.text"})
                assert json.loads(inbound.decrypt(content.ciphertext)[0])["content"]["body"] == "SDK outbound"
                assert (await store.get_outbound_group_session(outbound.room_id)).message_count == 1
        finally:
            await store.close()
