"""Actual SQLite adapter open/reopen; no SQLAlchemy, psycopg, Alembic or PG instance."""

import asyncio
import importlib.abc
import sys


class WithoutPG(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"sqlalchemy", "psycopg", "alembic"}:
            raise ModuleNotFoundError("PostgreSQL stack deliberately absent")


sys.meta_path.insert(0, WithoutPG())


async def main():
    import aiohttp
    from gateway.config import PlatformConfig
    from plugins.platforms.matrix.adapter import MatrixAdapter
    from mautrix.api import HTTPAPI
    from mautrix.client import Client
    from mautrix.client.state_store import MemoryStateStore
    from mautrix.crypto import InboundGroupSession, OutboundGroupSession
    from mautrix.types import QueryKeysResponse, EncryptionKeyAlgorithm
    remote, identity, saved = None, None, None
    for restart in range(2):
        adapter = MatrixAdapter(PlatformConfig(enabled=True, token="test-token", extra={"homeserver": "https://matrix.test",
            "user_id": "@bot:matrix.test", "device_id": "DEVICE", "e2ee_mode": "required"}))
        adapter._resolve_store_dir().mkdir(parents=True, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            api = HTTPAPI(base_url="https://matrix.test", client_session=session)
            client = Client(mxid="@bot:matrix.test", device_id="DEVICE", api=api, state_store=MemoryStateStore())
            async def query(*args, **kwargs):
                return QueryKeysResponse.deserialize({"device_keys": {} if remote is None else {str(client.mxid): {str(client.device_id): remote.serialize()}}, "failures": {}})
            async def upload(*args, device_keys=None, **kwargs):
                nonlocal remote
                if device_keys is not None:
                    remote = device_keys
                return {EncryptionKeyAlgorithm.SIGNED_CURVE25519: 50}
            async def reject_network(*args, **kwargs):
                raise AssertionError("Only local SDK transports are allowed")
            client.query_keys, client.upload_keys, api.request = query, upload, reject_network
            adapter._client = client
            try:
                assert await adapter._connect_setup_e2ee(client, api, client.state_store)
                assert adapter._encryption and client.crypto.account.shared
                store = client.crypto.crypto_store
                if restart == 0:
                    identity = client.crypto.account.identity_keys
                    outbound = OutboundGroupSession("!room:matrix.test")
                    outbound.shared = True
                    inbound = InboundGroupSession(outbound.session_key, client.crypto.account.signing_key, client.crypto.account.identity_key, outbound.room_id)
                    await store.put_group_session(inbound.room_id, inbound.sender_key, inbound.id, inbound)
                    saved = (inbound.room_id, inbound.id, outbound.encrypt("SQLite real SDK restart"))
                else:
                    assert client.crypto.account.identity_keys == identity
                    loaded = await store.get_group_session(saved[0], saved[1])
                    assert loaded.decrypt(saved[2])[0] == "SQLite real SDK restart"
                assert adapter._crypto_db_path.is_file()
            finally:
                await adapter.disconnect()
    assert not {"sqlalchemy", "psycopg", "alembic"}.intersection(sys.modules)
    print("MATRIX_SQLITE_WITHOUT_PG_OK")


asyncio.run(main())
