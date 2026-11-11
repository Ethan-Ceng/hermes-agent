"""Actual RetainDB writer and Matrix SDK encryption in the combined PG business process."""

import asyncio
import json
from threading import Event
from contextlib import asynccontextmanager


def retain(home, label, role):
    from plugins.memory.retaindb import _WriteQueue
    received, entered = [], Event()

    class Client:
        base_url, project = "https://local-test.example", "project"
        def ingest_session(self, user, session, messages):
            received.append(messages)
            entered.set()
            assert user == "same" and session == "same" and messages == [{"content": label}]
            if role == "write":
                raise OSError("acceptance remote unavailable; retain the pending row")
            return {"status": "ok"}

    if role == "write":
        from plugins.memory.retaindb.storage_schema import initialize_queue_schema
        initialize_queue_schema(profile_home=home)
    queue = _WriteQueue(Client(), home / "retaindb_queue.db", profile_home=home)
    try:
        if role == "write":
            queue.enqueue("same", "same", [{"content": label}])
        assert entered.wait(45), "persistent RetainDB queue did not deliver its captured payload"
    finally:
        queue.shutdown()
    assert not queue._thread.is_alive()
    assert received == [[{"content": label}]]


@asynccontextmanager
async def crypto_store(home, backend, role):
    database = None
    if backend == "postgresql":
        from tests.hermes_db.matrix_support import new_store
        store = new_store()
    else:
        from mautrix.crypto.store.asyncpg import PgCryptoStore
        from plugins.platforms.matrix.storage_schema import upgrade_crypto_schema, open_crypto_database
        path = home / "matrix-crypto.db"
        if role == "write":
            await upgrade_crypto_schema(path)
        database = await open_crypto_database(path)
        store = PgCryptoStore(account_id="@bot:matrix.test", pickle_key="isolated-test-key", db=database)
    try:
        await store.open()
        yield store
    finally:
        await store.close()
        if database is not None:
            await database.stop()


async def matrix(home, label, role, backend="postgresql"):
    from mautrix.crypto import InboundGroupSession, OutboundGroupSession
    from mautrix.types import EventType
    from tests.hermes_db.matrix_support import sdk_machine
    async with crypto_store(home, backend, role) as store:
        async with sdk_machine(store, device_id="DEVICE") as (machine, _client):
            if role == "write":
                outbound = OutboundGroupSession("!same:matrix.test")
                outbound.shared = True
                inbound = InboundGroupSession(outbound.session_key, machine.account.signing_key, machine.account.identity_key, outbound.room_id)
                fixture = dict(identity=machine.account.identity_keys, room=inbound.room_id, session=inbound.id, cipher=outbound.encrypt(label))
                await store.add_outbound_group_session(outbound)
                await store.put_group_session(inbound.room_id, inbound.sender_key, inbound.id, inbound)
                await store.put_next_batch(label)
                (home / "matrix-witness.json").write_text(json.dumps(fixture), encoding="utf-8")
            else:
                fixture = json.loads((home / "matrix-witness.json").read_text(encoding="utf-8"))
                assert machine.account.identity_keys == fixture["identity"]
                assert await store.get_next_batch() == label
                inbound = await store.get_group_session(fixture["room"], fixture["session"])
                assert inbound.decrypt(fixture["cipher"])[0] == label
                encrypted = await machine.encrypt_megolm_event(fixture["room"], EventType.ROOM_MESSAGE, {"msgtype": "m.text", "body": label})
                assert json.loads(inbound.decrypt(encrypted.ciphertext)[0])["content"]["body"] == label


def pg_plugins(home, label, role):
    retain(home, label, role)
    asyncio.run(matrix(home, label, role))
