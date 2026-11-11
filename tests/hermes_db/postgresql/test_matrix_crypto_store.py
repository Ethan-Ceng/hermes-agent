"""Real mautrix/libolm protocol values must survive PG reopen and Profile isolation."""

import pytest
import asyncio

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@pytest.mark.asyncio
async def test_real_olm_account_device_and_sync_token_reopen_on_pg(pg_profiles):
    from mautrix.crypto import OlmAccount
    from mautrix.types import DeviceID, SyncToken
    from plugins.plugin_storage import matrix_crypto_store as PostgresCryptoStore
    arguments = dict(account_id="@bot:matrix.test", device_id="DEVICE", homeserver="https://matrix.test", pickle_key="isolated-test-key")
    with pg_profiles("one"):
        store = PostgresCryptoStore(**arguments)
        await store.open()
        account = OlmAccount()
        account.shared = True
        account.generate_one_time_keys(2)
        await store.put_device_id(DeviceID("DEVICE"))
        await store.put_account(account)
        await store.put_next_batch(SyncToken("next\x00🙂"))
        await store.close()
        reopened = PostgresCryptoStore(**arguments)
        await reopened.open()
        try:
            loaded = await reopened.get_account()
            assert loaded.identity_keys == account.identity_keys and loaded.shared
            assert loaded.one_time_keys == account.one_time_keys
            sender = OlmAccount()
            outgoing = sender.new_outbound_session(loaded.identity_key, next(iter(loaded.one_time_keys["curve25519"].values())))
            message = outgoing.encrypt("PG-restored private one-time key")
            incoming = loaded.new_inbound_session(sender.identity_key, message.body)
            assert incoming.decrypt(message) == "PG-restored private one-time key"
            await reopened.put_account(loaded)
            assert len((await reopened.get_account()).one_time_keys["curve25519"]) == 1
            assert await reopened.get_device_id() == "DEVICE"
            assert await reopened.get_next_batch() == "next\x00🙂"
        finally:
            await reopened.close()
    with pg_profiles("two"):
        peer = PostgresCryptoStore(**arguments)
        await peer.open()
        try:
            assert await peer.get_account() is None
        finally:
            await peer.close()


@pytest.mark.asyncio
async def test_competing_replay_indices_have_one_winner_and_separate_profiles(pg_profiles):
    from tests.hermes_db.matrix_support import new_store
    with pg_profiles("one"):
        first, second = new_store(), new_store()
        await asyncio.gather(first.open(), second.open())
        try:
            results = await asyncio.gather(first.validate_message_index("sender", "session", "$one", 0, 1),
                second.validate_message_index("sender", "session", "$two", 0, 1))
            assert sum(results) == 1
            winner = "$one" if results[0] else "$two"
            assert await first.validate_message_index("sender", "session", winner, 0, 1)
        finally:
            await asyncio.gather(first.close(), second.close())
    with pg_profiles("two"):
        other = new_store()
        await other.open()
        try:
            assert await other.validate_message_index("sender", "session", "$other-profile", 0, 1)
        finally:
            await other.close()
