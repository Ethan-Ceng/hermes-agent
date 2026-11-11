"""Matrix-owned explicit SDK SQLite migrations and read-only schema readiness checks."""
import asyncio
from pathlib import Path
import sqlite3

from plugins.plugin_storage import StorageSchemaError, selected_storage_backend

# mautrix[encryption] 0.21.1 owns these tables and its ten-revision upgrade chain.
CRYPTO_TABLES = frozenset({
    'crypto_account', 'crypto_cross_signing_keys', 'crypto_cross_signing_signatures',
    'crypto_device', 'crypto_megolm_inbound_session', 'crypto_megolm_outbound_session',
    'crypto_message_index', 'crypto_olm_session', 'crypto_tracked_user',
})
_UPGRADE_HINT = 'Run `hermes matrix db upgrade` for this Profile.'


async def check_crypto_schema(database):
    from mautrix.crypto.store.asyncpg import PgCryptoStore
    expected = len(PgCryptoStore.upgrade_table.upgrades)
    try:
        version = await database.fetchval('SELECT version FROM crypto_version LIMIT 1')
    except sqlite3.DatabaseError:
        raise StorageSchemaError('Matrix crypto Schema is missing. ' + _UPGRADE_HINT) from None
    tables = {row['name'] for row in await database.fetch("SELECT name FROM sqlite_master WHERE type='table'")}
    if version != expected or not CRYPTO_TABLES.issubset(tables):
        raise StorageSchemaError('Matrix crypto Schema is not ready for the installed SDK. ' + _UPGRADE_HINT)
    return version


async def open_crypto_database(path):
    """Ordinary acquisition never attaches crypto upgrades or creates a missing file."""
    from mautrix.util.async_db import Database
    path = Path(path)
    if not path.is_file():
        raise StorageSchemaError('Matrix crypto Schema is missing. ' + _UPGRADE_HINT)
    database = Database.create(f'sqlite:///{path}')
    try:
        await database.start()
        await check_crypto_schema(database)
    except BaseException:
        await database.stop()
        raise
    return database


async def upgrade_crypto_schema(path):
    """Explicit setup/upgrade uses the original SDK migration resources unchanged."""
    from mautrix.crypto.store.asyncpg import PgCryptoStore
    from mautrix.util.async_db import Database
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database.create(f'sqlite:///{path}', upgrade_table=PgCryptoStore.upgrade_table)
    try:
        await database.start()
        return await check_crypto_schema(database)
    finally:
        await database.stop()


def crypto_db_path():
    from plugins.platforms.matrix.adapter import _get_hermes_dir
    return _get_hermes_dir('platforms/matrix/store', 'matrix/store') / 'crypto.db'


def setup_crypto_schema():
    if selected_storage_backend() == 'sqlite':
        asyncio.run(upgrade_crypto_schema(crypto_db_path()))


def register_cli(parser):
    commands = parser.add_subparsers(dest='matrix_command', required=True)
    database = commands.add_parser('db', help='Inspect or explicitly upgrade Matrix SDK crypto storage')
    actions = database.add_subparsers(dest='matrix_db_action', required=True)
    actions.add_parser('status', help='Check the existing crypto Schema without DDL')
    actions.add_parser('upgrade', help='Create or upgrade crypto Schema with the original SDK migrations')


def dispatch_cli(args):
    if selected_storage_backend() != 'sqlite':
        print('Matrix uses the selected PostgreSQL business Schema; use `hermes db status` or `hermes db upgrade`.')
        return 0
    try:
        version = asyncio.run(_run_schema_command(args.matrix_db_action))
    except StorageSchemaError as error:
        print(str(error))
        return 1
    print(f'Matrix crypto Schema ready at SDK revision {version}.')
    return 0


async def _run_schema_command(action):
    path = crypto_db_path()
    if action == 'upgrade':
        return await upgrade_crypto_schema(path)
    database = await open_crypto_database(path)
    try:
        return await check_crypto_schema(database)
    finally:
        await database.stop()

def register_commands(ctx):
    ctx.register_cli_command("matrix", "Inspect or upgrade Matrix crypto storage", register_cli, dispatch_cli)
