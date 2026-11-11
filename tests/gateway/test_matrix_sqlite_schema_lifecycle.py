"""Real SDK SQLite creation is explicit;ordinary reopen only checks schema and restores keys."""
import asyncio
import os
import re
import sqlite3
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.platforms('linux')]


@pytest.mark.asyncio
async def test_sdk_explicit_upgrade_no_ddl_open_and_new_process_restore(tmp_path, monkeypatch):
    from tests.hermes_db.matrix_support import sdk_machine
    from mautrix.crypto.store.asyncpg import PgCryptoStore
    from plugins.platforms.matrix.storage_schema import open_crypto_database, upgrade_crypto_schema

    path = tmp_path / 'profile' / 'platforms' / 'matrix' / 'store' / 'crypto.db'
    await upgrade_crypto_schema(path)
    statements = []
    original = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', traced_connect)
    database = await open_crypto_database(path)
    try:
        assert not database.upgrade_table.upgrades
        store = PgCryptoStore(account_id='@schema:example.org', pickle_key='fixture-only', db=database)
        await store.open()
        async with sdk_machine(store, device_id='SCHEMA') as (machine, _client):
            await store.put_account(machine.account)
            await store.put_next_batch('saved-token')
            assert await store.get_next_batch() == 'saved-token'
    finally:
        await database.stop()
    assert statements
    assert not [sql for sql in statements if re.match(r'\s*(CREATE|ALTER|DROP)\b', sql, re.IGNORECASE)]
    code = """
import asyncio,os,sys
from pathlib import Path
from mautrix.crypto.store.asyncpg import PgCryptoStore
from plugins.platforms.matrix.storage_schema import open_crypto_database
async def recover():
    database = await open_crypto_database(Path(sys.argv[1]))
    try:
        store = PgCryptoStore(account_id='@schema:example.org',pickle_key='fixture-only',db=database)
        await store.open()
        assert await store.get_account() is not None
        assert await store.get_next_batch() == 'saved-token'
        assert os.getpid() != int(sys.argv[2])
    finally:
        await database.stop()
asyncio.run(recover())
"""
    child_env = dict(os.environ, HERMES_HOME=str(tmp_path / 'child-home'), HERMES_RUNTIME_DIR=str(tmp_path / 'child-runtime'))
    child = await asyncio.to_thread(subprocess.run, [sys.executable, '-c', code, str(path), str(os.getpid())],
                           env=child_env, capture_output=True, text=True, timeout=30, check=False)
    assert child.returncode == 0, child.stderr


@pytest.mark.asyncio
async def test_sdk_open_missing_schema_preserves_absent_database(tmp_path):
    from plugins.platforms.matrix.storage_schema import open_crypto_database
    from plugins.plugin_storage import StorageSchemaError

    path = tmp_path / 'absent' / 'crypto.db'
    with pytest.raises(StorageSchemaError, match='matrix db upgrade'):
        await open_crypto_database(path)
    assert not path.exists() and not path.parent.exists()


@pytest.mark.asyncio
async def test_sdk_open_stale_schema_requires_explicit_upgrade(tmp_path):
    from plugins.platforms.matrix.storage_schema import open_crypto_database, upgrade_crypto_schema
    from plugins.plugin_storage import StorageSchemaError

    path = tmp_path / 'crypto.db'
    await upgrade_crypto_schema(path)
    with sqlite3.connect(path) as connection:
        version = connection.execute('SELECT version FROM crypto_version').fetchone()[0]
        connection.execute('UPDATE crypto_version SET version=?', (version - 1,))
    with pytest.raises(StorageSchemaError, match='matrix db upgrade'):
        await open_crypto_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT version FROM crypto_version').fetchone()[0] == version - 1

@pytest.mark.asyncio
async def test_adapter_missing_schema_preserves_legacy_pickle(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from plugins.platforms.matrix import adapter
    from plugins.platforms.matrix.adapter_crypto_sqlite import connect_sqlite

    monkeypatch.setattr(adapter, "_check_e2ee_deps", lambda: True)
    legacy = tmp_path / "crypto_store.pickle"
    legacy.write_bytes(b"legacy-fixture")
    owner = SimpleNamespace(
        _encryption=True, _e2ee_mode="required", _store_dir=tmp_path,
        _crypto_db_path=tmp_path / "crypto.db", _e2ee_setup_failed=AsyncMock(return_value=False),
    )
    assert await connect_sqlite(owner, object(), object(), object()) is False
    assert legacy.read_bytes() == b"legacy-fixture"
    assert not owner._crypto_db_path.exists()
    owner._e2ee_setup_failed.assert_awaited_once()
