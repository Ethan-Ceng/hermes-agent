"""Actual libolm ciphertext/ratchets and replay decisions must survive PG reopen."""

from datetime import UTC, datetime, timedelta, timezone
import pytest
from tests.hermes_db.matrix_support import new_store, olm_pair, group_pair

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_olm_sessions_resume_both_directions_with_exact_metadata(pg_profiles):
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        alice, bob, outbound, inbound = olm_pair()
        outbound.creation_time = datetime(2024, 3, 7, 9, 3, 4, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        await store.add_session(bob.identity_key, outbound)
        await store.add_session(alice.identity_key, inbound)
        assert await store.has_session(bob.identity_key)
        assert not await store.has_session("missing")
        assert await store.get_latest_session("missing") is None
        await store.close()
        store = new_store()
        await store.open()
        try:
            loaded = await store.get_latest_session(bob.identity_key)
            assert loaded.creation_time.isoformat() == outbound.creation_time.isoformat()
            assert inbound.decrypt(loaded.encrypt("after reopen")) == "after reopen"
            answer = inbound.encrypt("answer")
            loaded_inbound = (await store.get_sessions(alice.identity_key))[0]
            await store.update_session(alice.identity_key, inbound)
            assert loaded.decrypt(answer) == "answer"
            assert loaded_inbound.id == inbound.id
            await store.update_session(bob.identity_key, loaded)
            assert (await store.get_latest_session(bob.identity_key)).last_encrypted == loaded.last_encrypted
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_megolm_ratchets_outbound_counts_and_replay_are_persistent(pg_profiles):
    from mautrix.crypto.sessions import RatchetSafety
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        outbound, inbound = group_pair()
        inbound.forwarding_chain = ["forward\x00🙂"]
        inbound.ratchet_safety = RatchetSafety(5, [1, 3], [2])
        inbound.max_age = timedelta(days=2, seconds=4, microseconds=7)
        inbound.max_messages = 17
        inbound.received_at = datetime(2025, 1, 2, 3, 4, 5, 123457, tzinfo=UTC)
        outbound.max_age = timedelta(days=3, microseconds=9)
        outbound.shared = True
        await store.put_group_session(inbound.room_id, inbound.sender_key, inbound.id, inbound)
        await store.add_outbound_group_session(outbound)
        cipher = outbound.encrypt("persisted group 🙂")
        await store.update_outbound_group_session(outbound)
        assert await store.validate_message_index(inbound.sender_key, inbound.id, "$first", 0, 123)
        await store.close()
        store = new_store()
        await store.open()
        try:
            recovered = await store.get_group_session(inbound.room_id, inbound.id)
            assert recovered.decrypt(cipher)[0] == "persisted group 🙂"
            assert recovered.forwarding_chain == inbound.forwarding_chain
            assert recovered.ratchet_safety == inbound.ratchet_safety
            assert recovered.received_at == inbound.received_at and recovered.max_age == inbound.max_age
            assert recovered.max_messages == 17
            sending = await store.get_outbound_group_session(outbound.room_id)
            assert sending.shared and sending.message_count == 1 and sending.max_age == outbound.max_age
            assert recovered.decrypt(sending.encrypt("next message"))[0] == "next message"
            assert await store.validate_message_index(inbound.sender_key, inbound.id, "$first", 0, 123)
            assert not await store.validate_message_index(inbound.sender_key, inbound.id, "$other", 0, 123)
            assert not await store.validate_message_index(inbound.sender_key, inbound.id, "$first", 0, 124)
            await store.remove_outbound_group_sessions([outbound.room_id])
            assert await store.get_outbound_group_session(outbound.room_id) is None
            await store.add_outbound_group_session(outbound)
            await store.remove_outbound_group_session(outbound.room_id)
            assert await store.get_outbound_group_session(outbound.room_id) is None
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_redaction_tombstones_and_scheduled_expiry_scope(pg_profiles):
    from mautrix.errors import GroupSessionWithheldError
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        sessions = []
        for number in range(4):
            _, session = group_pair(f"!room{number}:matrix.test")
            session.received_at = datetime(2001, 1, 1)
            session.max_age = timedelta(days=1)
            session.is_scheduled = number == 1
            if number == 2:
                session.received_at = None
            await store.put_group_session(session.room_id, session.sender_key, session.id, session)
            sessions.append(session)
        try:
            assert set(await store.redact_expired_group_sessions()) == {sessions[0].id, sessions[3].id}
            assert await store.redact_outdated_group_sessions() == [sessions[2].id]
            with pytest.raises(GroupSessionWithheldError):
                await store.get_group_session(sessions[0].room_id, sessions[0].id)
            assert not await store.has_group_session(sessions[0].room_id, sessions[0].id)
            await store.redact_group_session("!wrong:matrix.test", sessions[1].id, "wrong scope")
            assert await store.has_group_session(sessions[1].room_id, sessions[1].id)
            assert await store.redact_group_sessions(sessions[1].room_id, None, "keep scheduled") == []
            sessions[1].is_scheduled = False
            await store.put_group_session(sessions[1].room_id, sessions[1].sender_key, sessions[1].id, sessions[1])
            assert await store.redact_group_sessions(None, sessions[1].sender_key, "removed") == [sessions[1].id]
            with pytest.raises(ValueError):
                await store.redact_group_sessions(None, None, "unsafe")
            await store.put_group_session(sessions[0].room_id, sessions[0].sender_key, sessions[0].id, sessions[0])
            await store.redact_group_session(sessions[0].room_id, sessions[0].id, "explicit")
            assert not await store.has_group_session(sessions[0].room_id, sessions[0].id)
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_latest_olm_session_follows_decrypt_activity_after_reopen(pg_profiles):
    with pg_profiles("one"):
        store = new_store()
        await store.open()
        alice, bob, first, _ = olm_pair()
        bob.generate_one_time_keys(1)
        second = alice.new_outbound_session(bob.identity_key, next(iter(bob.one_time_keys["curve25519"].values())))
        first.last_decrypted, second.last_decrypted = datetime(2024, 1, 1), datetime(2024, 1, 2)
        await store.add_session(bob.identity_key, first)
        await store.add_session(bob.identity_key, second)
        await store.close()
        store = new_store()
        await store.open()
        try:
            assert (await store.get_latest_session(bob.identity_key)).id == second.id
            first.last_decrypted = datetime(2024, 1, 3)
            await store.update_session(bob.identity_key, first)
            assert [session.id for session in await store.get_sessions(bob.identity_key)] == [first.id, second.id]
        finally:
            await store.close()
