"""Fresh interpreter restores actual Matrix encryption without either SDK SQL driver."""

import asyncio
import importlib.abc
import json
from pathlib import Path
import sqlite3
import sys

attempts = []


def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("SQLite forbidden in Matrix PostgreSQL business process")


class WithoutSDKDrivers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"asyncpg", "aiosqlite"}:
            raise ModuleNotFoundError("SDK SQL drivers deliberately absent")


sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == "sqlite3.connect" else None)
sys.meta_path.insert(0, WithoutSDKDrivers())


async def main():
    from hermes_constants import get_hermes_home
    from plugins.platforms.matrix.adapter_storage import pg_dependencies_available
    from plugins.platforms.matrix.adapter import ensure_matrix_deps
    from pm import extras
    from tests.hermes_db.matrix_support import new_store, sdk_machine
    from mautrix.types import EventType
    assert pg_dependencies_available()
    def no_install(extra):
        raise AssertionError("PG Matrix dependency check attempted to install SDK SQL drivers")
    extras.ensure_import = no_install
    assert ensure_matrix_deps()
    fixture = json.loads((Path(get_hermes_home()) / "matrix-fixture.json").read_text(encoding="utf-8"))
    store = new_store()
    await store.open()
    try:
        assert (await store.get_account()).identity_keys == fixture["identity"]
        assert await store.get_next_batch() == "new-process\x00🙂"
        inbound = await store.get_group_session(fixture["room"], fixture["session"])
        assert inbound.decrypt(fixture["cipher"])[0] == "new-process group plaintext"
        async with sdk_machine(store) as (machine, _):
            encrypted = await machine.encrypt_megolm_event(fixture["room"], EventType.ROOM_MESSAGE, {"msgtype": "m.text", "body": "restarted SDK encryption"})
            assert json.loads(inbound.decrypt(encrypted.ciphertext)[0])["content"]["body"] == "restarted SDK encryption"
        assert (await store.get_outbound_group_session(fixture["room"])).message_count == 2
        assert "aiosqlite" not in sys.modules and "asyncpg" not in sys.modules
        assert not attempts
    finally:
        await store.close()
    print("PG_MATRIX_SDK_RESTART_OK")


asyncio.run(main())
