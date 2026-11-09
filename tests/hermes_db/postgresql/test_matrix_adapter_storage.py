"""Real SDK adapter startup keeps crypto in PG and preserves legacy data/remote devices."""

from contextlib import asynccontextmanager
import pytest
from tests.hermes_db.matrix_support import current_engine

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


@asynccontextmanager
async def adapter_client(monkeypatch, *, server_account=None, mode="required"):
    import aiohttp
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter
    from plugins.platforms.matrix.adapter_storage import make_client
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.types import QueryKeysResponse, EncryptionKeyAlgorithm
    adapter = MatrixAdapter(PlatformConfig(enabled=True, token="isolated-token", extra={
        "homeserver": "https://matrix.test", "user_id": "@bot:matrix.test", "device_id": "DEVICE", "e2ee_mode": mode}))
    adapter._resolve_store_dir().mkdir(parents=True, exist_ok=True)
    legacy = {adapter._store_dir / name: b"untouched legacy bytes" for name in ("crypto.db", "crypto_store.pickle")}
    for path, body in legacy.items():
        path.write_bytes(body)
    engine = current_engine()
    remote = {"keys": None if server_account is None else server_account.get_device_keys("@bot:matrix.test", "DEVICE")}
    async with aiohttp.ClientSession() as session:
        api = HTTPAPI(base_url="https://matrix.test", client_session=session)
        state = MemoryStateStore()
        client = make_client(Client, adapter, mxid="@bot:matrix.test", device_id="DEVICE", api=api, state_store=state)
        async def query(*args, **kwargs):
            assert engine.pool.checkedout() == 0
            return QueryKeysResponse.deserialize({"device_keys": {} if remote["keys"] is None else {str(client.mxid): {str(client.device_id): remote["keys"].serialize()}}, "failures": {}})
        async def upload(*args, device_keys=None, **kwargs):
            assert engine.pool.checkedout() == 0
            if device_keys is not None:
                remote["keys"] = device_keys
            return {EncryptionKeyAlgorithm.SIGNED_CURVE25519: 50}
        async def no_remote_delete(*args, **kwargs):
            raise AssertionError("PG Matrix startup must never delete or reset remote devices")
        monkeypatch.setattr(client, "query_keys", query)
        monkeypatch.setattr(client, "upload_keys", upload)
        monkeypatch.setattr(api, "request", no_remote_delete)
        adapter._client = client
        try:
            yield adapter, client, api, state, remote
        finally:
            await adapter.disconnect()
            for path, body in legacy.items():
                assert path.read_bytes() == body


@pytest.mark.asyncio
async def test_adapter_actual_sdk_pg_startup_and_reopen(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _):
            assert await adapter._connect_setup_e2ee(client, api, state)
            identity = client.crypto.account.identity_keys
            assert client.crypto.account.shared and adapter._encryption
            assert client.sync_store is client.crypto.crypto_store
            await client.sync_store.put_next_batch("adapter-restart")
            diagnostics = adapter.get_diagnostics()["e2ee"]
            assert diagnostics["backend"] == "postgresql" and diagnostics["crypto_store_path"] is None
            remote_account = await client.crypto.crypto_store.get_account()
        async with adapter_client(monkeypatch, server_account=remote_account) as (adapter, client, api, state, _):
            assert await adapter._connect_setup_e2ee(client, api, state)
            assert client.crypto.account.identity_keys == identity
            assert await client.sync_store.get_next_batch() == "adapter-restart"


@pytest.mark.asyncio
async def test_fresh_pg_dataset_refuses_existing_remote_device_even_optional(pg_profiles, monkeypatch):
    from mautrix.crypto import OlmAccount
    with pg_profiles("one"):
        remote_account = OlmAccount()
        async with adapter_client(monkeypatch, server_account=remote_account, mode="optional") as (adapter, client, api, state, remote):
            assert not await adapter._connect_setup_e2ee(client, api, state)
            assert adapter._encryption and client.crypto is None
            assert remote["keys"].ed25519 == remote_account.signing_key


@pytest.mark.asyncio
async def test_optional_mode_pg_storage_fault_is_fatal_not_plaintext(pg_profiles, monkeypatch):
    from hermes_db.errors import StorageUnavailableError
    import hermes_db.domains.plugin_storage.matrix.postgres.crypto as module
    def unavailable(reference):
        raise StorageUnavailableError("isolated database unavailable")
    with pg_profiles("one"):
        monkeypatch.setattr(module, "initialize", unavailable)
        async with adapter_client(monkeypatch, mode="optional") as (adapter, client, api, state, _):
            assert not await adapter._connect_setup_e2ee(client, api, state)
            assert adapter._encryption and client.crypto is None


@pytest.mark.asyncio
async def test_sdk_swallowed_storage_error_cannot_advance_durable_sync_cursor(pg_profiles, monkeypatch):
    from hermes_db.errors import StorageUnavailableError
    from mautrix.types import EventType
    from tests.hermes_db.matrix_support import group_pair
    import hermes_db.domains.plugin_storage.matrix.postgres.operations.sessions as operations
    with pg_profiles("one"):
        async with adapter_client(monkeypatch) as (adapter, client, api, state, _):
            assert await adapter._connect_setup_e2ee(client, api, state)
            store = client.crypto.crypto_store
            await store.put_next_batch("before-failed-handler")
            _, inbound = group_pair()
            async def persist(event):
                await store.put_group_session(inbound.room_id, inbound.sender_key, inbound.id, inbound)
            client.add_event_handler(EventType.ROOM_MESSAGE, persist)
            original = operations.put_group_session
            def unavailable(*args, **kwargs):
                raise StorageUnavailableError("injected sync crypto write failure")
            monkeypatch.setattr(operations, "put_group_session", unavailable)
            sync = {"next_batch": "after-handler", "device_one_time_keys_count": {"signed_curve25519": 50}, "rooms": {"join": {
                inbound.room_id: {"timeline": {"events": [{"type": "m.room.message", "sender": "@peer:matrix.test", "event_id": "$handler",
                    "origin_server_ts": 123, "content": {"msgtype": "m.text", "body": "persist"}}]}}}}}
            with pytest.raises(StorageUnavailableError):
                await adapter._absorb_sync(client, sync)
            assert await store.get_next_batch() == "before-failed-handler"
            monkeypatch.setattr(operations, "put_group_session", original)
            assert await adapter._absorb_sync(client, sync) == "after-handler"
            assert await store.has_group_session(inbound.room_id, inbound.id)
            assert await store.get_next_batch() == "after-handler"
