"""Per-plugin persistent storage: ``<hermes home>/plugin-data/<name>/``.

Plugins must NOT park state in ``<hermes home>/plugins/<name>/`` (the install dir, deleted by
``remove`` and git-pulled by ``update``). Secrets are deliberately NOT part of this convention —
credential reads go through ``agent.secret_scope`` / ``.env``.
Usage: ``plugin_data_dir("my-plugin") / "state.json"``; ``plugin_db("my-plugin")`` → ``data.db``.
"""

from __future__ import annotations

from contextlib import contextmanager
import re
import datetime as dt
import threading
import hashlib
import json
import sqlite3
from pathlib import Path
from hermes_db.errors import StorageSchemaError, StorageConfigurationError, StorageError, UnknownCommitError, StorageConflictError
from agent.runtime_session_store import WorkerPersistenceError
from . import plugin_storage_types as contract
from hermes_db.domains.plugin_storage.records.api import PluginRef
from hermes_db.domains.plugin_storage.discord.api import DiscordRef
from hermes_db.domains.plugin_storage.matrix.api import MatrixRef
from hermes_db.domains.plugin_storage.retain.api import RetainQueueRef
from .plugin_storage_types import PluginRecord, PluginStorageConflict, PluginStorageQuotaError, PluginStore

__all__ = ["PluginRecord", "PluginStorageConflict", "PluginStorageQuotaError", "PluginStore", "StorageConfigurationError", 'StorageError', "StorageSchemaError", 'UnknownCommitError', 'WorkerPersistenceError', 'WorkerRetainQueueRef', 'capture_discord', 'capture_matrix', 'capture_plugin', 'capture_queue', "configure_plugin_sqlite", 'discord_recovery_store', "initialize_plugin_database", "initialize_plugin_store", "initialize_selected_plugin_stores", 'matrix_crypto_store', 'matrix_dependencies_available', 'open_discord', 'open_plugin', "open_plugin_database", 'open_queue', "plugin_data_dir", "plugin_db", 'plugin_profile_scope', "plugin_sqlite_transaction", "plugin_store", 'redact_storage_error', 'resource_for', 'retain_acknowledge', 'retain_claim', 'retain_counts', 'retain_enqueue', 'retain_fail', 'retain_inspect', 'retain_owns_claim', 'retain_prepare', 'retain_ready', 'retain_renew', "selected_storage_backend", "session_history", 'spawn_plugin_thread', 'storage_profile', 'unit_of_work', "upgrade_plugin_stores"]

# Mirrors the plugin-name shape `hermes plugins install` accepts (no separators/traversal).
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _validate_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name) or ".." in name:
        raise ValueError(f"invalid plugin name for storage: {name!r}")
    return name


def plugin_data_dir(name: str) -> Path:
    """Return (and create) ``<hermes home>/plugin-data/<name>/``; resolves ``get_hermes_home()`` on
    every call so it follows the active profile — don't cache across profile switches."""
    from hermes_constants import get_hermes_home
    root = get_hermes_home() / "plugin-data" / _validate_name(name)
    root.mkdir(parents=True, exist_ok=True)
    return root


def plugin_db(name: str, filename: str = "data.db") -> sqlite3.Connection:
    """Open ``<data dir>/<filename>``. WAL so a dashboard reader and a tool writer coexist;
    ``check_same_thread=False`` for the threaded FastAPI/tool env — caller owns transactions."""
    if Path(filename).name != filename or not filename:
        raise ValueError(f"invalid plugin db filename: {filename!r}")
    _validate_name(name)
    from hermes_cli.db_setup import storage_backend
    if storage_backend() != "sqlite":
        from hermes_db.errors import StorageConfigurationError
        raise StorageConfigurationError(f"Plugin {name} uses the SQLite-only plugin_db API; use plugin_store or its portable domain storage")
    from hermes_cli.db_sqlite_policy import open_profile_sqlite as open_db

    # WAL via the shared fallback helper: network filesystems degrade to DELETE and WAL-reset-bug
    # builds never enable it, instead of every plugin DB bypassing those rules with a raw PRAGMA.
    return open_db(plugin_data_dir(name) / filename, db_label=f"plugin-data/{name}/{filename}",
                   foreign_keys=True, row_factory=None, check_same_thread=False)


def plugin_store(name: str, *, namespace: str = "default", profile_home: Path | None = None) -> PluginStore:
    """Capture one Profile/plugin/namespace with portable JSON, exact revision CAS and TTL.

    expected_revision=0 creates an absent record; None writes unconditionally. A stale
    revision raises PluginStorageConflict. scan uses the last returned key as `after`.
    """
    from hermes_cli.db_setup import storage_backend
    from hermes_constants import get_hermes_home
    _validate_name(name)
    _validate_name(namespace)
    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    if storage_backend(home) == "postgresql":
        return PostgresPluginStore(name, namespace, home)
    from hermes_db.domains.plugin_storage.records.sqlite import SQLitePluginStore
    from functools import partial
    path = home / "plugin-data" / name / "portable.db"
    return SQLitePluginStore(name, namespace, home, connection=partial(_plugin_sqlite_connection, home, path))


@contextmanager
def plugin_sqlite_transaction(conn):
    """Commit or roll back an explicit legacy SQLite plugin operation without closing its connection."""
    from hermes_db.infra.sqlite.transactions import write_txn
    with write_txn(conn):
        yield conn


def configure_plugin_sqlite(conn, *, db_label):
    """Apply the active Profile's WAL safety policy to an existing legacy plugin connection."""
    from hermes_cli.db_sqlite_policy import apply_wal_with_fallback
    return apply_wal_with_fallback(conn, db_label=db_label)


@contextmanager
def session_history(*, profile_home: Path | None = None):
    """Acquire history and its dataset identity for a plugin scan; release this view on exit."""
    from hermes_cli.db_sessions import open_session_store
    from hermes_db.health import storage_identity
    from hermes_constants import get_hermes_home

    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    store = open_session_store(db_path=home / "state.db", read_only=True)
    try:
        yield store, storage_identity(store)
    finally:
        store.close()


def selected_storage_backend(profile_home=None):
    """Return the selected backend under the application-owned Profile configuration."""
    from hermes_cli.db_setup import storage_backend
    return storage_backend(profile_home)


def capture_plugin(plugin_id, namespace, profile_home):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with acquire_profile_domain("plugins", profile_home=profile_home) as resource:
        return PluginRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions), plugin_id, namespace)


@contextmanager
def open_plugin(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("plugins", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured plugin backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured plugin database target changed; reopen its owning runtime")
        with (resource.write() if write else resource.read()) as conn:
            yield conn


def capture_discord(profile_home):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with acquire_profile_domain("discord_recovery", profile_home=profile_home) as resource:
        return DiscordRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions))


@contextmanager
def open_discord(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("discord_recovery", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured Discord backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured Discord database target changed; reopen its owning adapter")
        with (resource.write() if write else resource.read()) as conn:
            yield conn


def capture_matrix(profile_home, homeserver, account_id, device_id):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_cli.db_sessions import _owner_only
    from hermes_db.infra.postgresql.engine import get_engine
    from hermes_db.core.values import resource_key
    from hermes_db.infra.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA
    _owner_only()
    if not homeserver or not account_id or not device_id:
        raise StorageConfigurationError("PG Matrix encryption requires authenticated homeserver, user and device identities")
    settings, scope = resolve_db_configuration(profile_home)
    if settings.backend != "postgresql":
        raise StorageConfigurationError("The selected Matrix CryptoStore requires PostgreSQL storage")
    pg = settings.postgresql
    target = resource_key(Transactions(get_engine(pg), pg.schema, schema_token=SCHEMA))
    return MatrixRef(scope.profile_home, scope.require_store_id(), target,
        hashlib.sha256(json.dumps([homeserver.rstrip("/"), account_id], ensure_ascii=True, separators=(",", ":")).encode()).hexdigest(), device_id)


@contextmanager
def resource_for(reference):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("matrix_crypto", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured Matrix backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured Matrix database target changed; reopen its owning adapter")
        yield resource


@contextmanager
def unit_of_work(reference, *, write=False):
    from hermes_db.domains.plugin_storage.matrix.postgres.queries.crypto import check_generation
    with resource_for(reference) as resource, (resource.write() if write else resource.read()) as conn:
        check_generation(conn, reference, lock=write)
        yield conn


class WorkerRetainQueueRef(RetainQueueRef):
    __slots__ = ('_resource',)

    def __init__(self, resource, destination_id):
        super().__init__(resource.scope.profile_home, resource.scope.require_store_id(), resource.target, destination_id)
        object.__setattr__(self, '_resource', resource)

    def _result(self, result):
        if isinstance(result, dict) and isinstance(result.get('fingerprint'), str):
            return dict(result, fingerprint=bytes.fromhex(result['fingerprint']))
        return result

    def command(self, name, **values):
        return self._result(self._resource.command('retain_queue.' + name, dict(destination_id=self.destination_id, **values)))

    def query(self, name, **values):
        return self._result(self._resource.query('retain_queue.' + name, dict(destination_id=self.destination_id, **values)))


def capture_queue(profile_home, destination_id):
    from agent.runtime_domain_store import worker_resource
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    worker = worker_resource('retain_queue', profile_home=profile_home)
    if worker is not None:
        return WorkerRetainQueueRef(worker, destination_id)
    with acquire_profile_domain("retain_queue", profile_home=profile_home) as resource:
        return RetainQueueRef(resource.scope.profile_home, resource.scope.require_store_id(), resource_key(resource._transactions), destination_id)


@contextmanager
def open_queue(reference, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.core.values import resource_key
    with _owning_profile(reference.profile_home), acquire_profile_domain("retain_queue", profile_home=reference.profile_home) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.store_id != reference.store_id:
            raise StorageConfigurationError("Captured RetainDB backend or store_id changed")
        if resource_key(resource._transactions) != reference.target:
            raise StorageConfigurationError("Captured RetainDB database target changed; reopen its owning provider")
        with (resource.write() if write else resource.read()) as conn:
            yield conn


class PostgresPluginStore:

    def __init__(self, plugin_id, namespace, profile_home):
        self.reference = capture_plugin(plugin_id, namespace, profile_home)

    def get(self, key):
        from hermes_db.domains.plugin_storage.records.postgres import store as record_sql
        key = contract.validate_key(key)
        with open_plugin(self.reference) as conn:
            return record_sql.get(conn, self.reference, key)

    def put(self, key, value, *, expected_revision=None, ttl_seconds=None):
        from hermes_db.domains.plugin_storage.records.postgres import store as record_sql
        key, data = (contract.validate_key(key), contract.encode_value(value))
        contract.validate_revision(expected_revision)
        contract.validate_ttl(ttl_seconds)
        with open_plugin(self.reference, write=True) as conn:
            return record_sql.put(conn, self.reference, key, data, expected_revision, ttl_seconds)

    def delete(self, key, *, expected_revision=None):
        from hermes_db.domains.plugin_storage.records.postgres import store as record_sql
        key = contract.validate_key(key)
        contract.validate_revision(expected_revision)
        with open_plugin(self.reference, write=True) as conn:
            return record_sql.remove(conn, self.reference, key, expected_revision)

    def scan(self, *, after=None, prefix='', limit=100):
        from hermes_db.domains.plugin_storage.records.postgres import store as record_sql
        after = None if after is None else contract.validate_key(after)
        prefix = contract.validate_key(prefix, empty=True)
        contract.validate_limit(limit)
        with open_plugin(self.reference) as conn:
            return record_sql.scan(conn, self.reference, after, prefix, limit)

    def prune_expired(self, *, limit=200):
        from hermes_db.domains.plugin_storage.records.postgres import store as record_sql
        contract.validate_limit(limit)
        with open_plugin(self.reference, write=True) as conn:
            return record_sql.prune(conn, self.reference, limit)


_DISCORD_READS = frozenset({"probe", "is_complete", "active_claim", "attempts_exhausted", "cursor"})

class PostgresDiscordRecoveryStore:
    def __init__(self, hermes_home=None):
        self.reference = capture_discord(hermes_home)
        self._hermes_home = self.reference.profile_home
        self._lock, self._initialized = threading.Lock(), False

    def path(self):
        raise StorageConfigurationError("PG Discord recovery has no SQLite database path")

    def call(self, fn, default=None):
        raise StorageConfigurationError("PG Discord recovery exposes named operations, not SQLite Connection callbacks")

    def _initialize(self):
        from hermes_db.domains.plugin_storage.discord.postgres.operations import recovery as operations
        from hermes_db.domains.plugin_storage.discord.postgres.queries.recovery import lock_store
        with self._lock:
            if not self._initialized:
                cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=30)).isoformat()
                with open_discord(self.reference, write=True) as conn:
                    lock_store(conn, self.reference)
                    operations.prune(conn, self.reference, cutoff=cutoff)
                self._initialized = True

    def _operation(self, name, *, default=None, **fields):
        from hermes_db.domains.plugin_storage.discord.postgres.operations import recovery as operations
        from hermes_db.domains.plugin_storage.discord.postgres.queries.recovery import lock_store
        self._initialize()
        with open_discord(self.reference, write=name not in _DISCORD_READS) as conn:
            if name not in _DISCORD_READS:
                lock_store(conn, self.reference)
            return getattr(operations, name)(conn, self.reference, **fields)


def discord_recovery_store(profile_home=None):
    return PostgresDiscordRecoveryStore(profile_home)


def plugin_profile_scope(profile_home):
    from hermes_cli.db_setup import _owning_profile
    return _owning_profile(profile_home)


def spawn_plugin_thread(target, *, name):
    from agent.memory_provider import spawn_context_thread
    return spawn_context_thread(target, name=name)


def redact_storage_error(text):
    from agent.redact import redact_sensitive_text
    return redact_sensitive_text(text, force=True, redact_url_credentials=True)


def matrix_crypto_store(*, account_id, device_id, homeserver, pickle_key, profile_home=None):
    """Construct the real SDK persistence adapter with an application-captured owner."""
    from hermes_constants import get_hermes_home
    from hermes_db.domains.plugin_storage.matrix.postgres.crypto import PostgresCryptoStore
    from hermes_cli.db_matrix_runtime import MatrixRuntime
    def runtime_factory(reference):
        return MatrixRuntime(reference, unit_of_work)
    reference = capture_matrix(profile_home or get_hermes_home(), homeserver, account_id, device_id)
    return PostgresCryptoStore(account_id=account_id, pickle_key=pickle_key, reference=reference,
        initialize=_initialize_matrix, runtime_factory=runtime_factory)


def _initialize_matrix(reference):
    from hermes_db.domains.plugin_storage.matrix.postgres.queries.crypto import initialize
    with resource_for(reference) as resource, resource.write() as conn:
        return initialize(conn, reference)


def matrix_dependencies_available():
    try:
        from hermes_db.domains.plugin_storage.matrix.postgres.crypto import PostgresCryptoStore
        import psycopg
    except ImportError:
        return False
    return True


def storage_profile(profile_home=None):
    from hermes_cli.db_setup import _owning_profile, resolve_db_configuration
    from hermes_constants import get_hermes_home
    home = get_hermes_home() if profile_home is None else profile_home
    with _owning_profile(home):
        settings, scope = resolve_db_configuration(home)
    return scope.profile_home, settings.backend


def retain_enqueue(reference, record):
    from hermes_db.core.values import decode_text
    if isinstance(reference, WorkerRetainQueueRef):
        if record['destination_id'] != reference.destination_id:
            raise StorageConflictError('RetainDB enqueue destination changed')
        return reference.command('enqueue', request_id=record['request_id'], user_id=decode_text(record['user_id']),
            session_id=decode_text(record['session_id']), messages=json.loads(decode_text(record['messages_json'])))
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference, write=True) as conn:
        return queue_sql.enqueue(reference, record, connection=conn)


def retain_ready(reference):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('ready')
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference) as conn:
        return queue_sql.ready(reference, connection=conn)


def retain_claim(reference):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('claim') if retain_ready(reference) else None
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference, write=True) as conn:
        return queue_sql.claim(reference, connection=conn)


def retain_renew(reference, request_id, token):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('renew', request_id=request_id, token=token)
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference, write=True) as conn:
        return queue_sql.renew(reference, request_id, token, connection=conn)


def retain_owns_claim(reference, request_id, token):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('owns_claim', request_id=request_id, token=token)
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference) as conn:
        return queue_sql.owns_claim(reference, request_id, token, connection=conn)


def retain_acknowledge(reference, request_id, token):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('acknowledge', request_id=request_id, token=token)
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference, write=True) as conn:
        return queue_sql.acknowledge(reference, request_id, token, connection=conn)


def retain_fail(reference, request_id, token, error):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('fail', request_id=request_id, token=token, error=error)
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference, write=True) as conn:
        return queue_sql.fail(reference, request_id, token, error, connection=conn)


def retain_inspect(reference, request_id):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('inspect', request_id=request_id)
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference) as conn:
        return queue_sql.inspect(reference, request_id, connection=conn)


def retain_counts(reference):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('counts')
    from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as queue_sql
    with open_queue(reference) as conn:
        return queue_sql.counts(reference, connection=conn)


def retain_prepare(reference, request_id, user_id, session_id, messages):
    from hermes_db.domains.plugin_storage.retain.postgres.operations.queue import prepare
    return prepare(reference, request_id, user_id, session_id, messages)


@contextmanager
def _plugin_sqlite_connection(profile_home, path, *, write=False):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_sqlite_policy import open_ready_profile_sqlite
    from hermes_db.domains.plugin_storage.records.sqlite import schema_ready
    from hermes_db.infra.sqlite.transactions import write_txn
    with _owning_profile(profile_home):
        if selected_storage_backend(profile_home) != 'sqlite':
            raise StorageConfigurationError('Captured SQLite plugin backend changed;reopen its owning store')
        conn = open_ready_profile_sqlite(path, db_label='plugin portable storage', ready=schema_ready, foreign_keys=True)
        try:
            if write:
                with write_txn(conn):
                    yield conn
            else:
                yield conn
        finally:
            conn.close()


def initialize_plugin_store(name, *, profile_home=None):
    """Explicit install/setup/upgrade of a plugin's selected portable dataset."""
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_sessions import _owner_only
    from hermes_cli.db_sqlite_policy import initialize_profile_sqlite
    from hermes_constants import get_hermes_home, mkdir_under_hermes_home
    from hermes_db.domains.plugin_storage.records.sqlite import initialize_schema
    _owner_only()
    _validate_name(name)
    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    if selected_storage_backend(home) == 'postgresql':
        capture_plugin(name, 'default', home)
        return
    with _owning_profile(home):
        path = home / 'plugin-data' / name / 'portable.db'
        mkdir_under_hermes_home(path.parent)
        initialize_plugin_database(path, db_label='plugin portable storage', initialize=initialize_schema,
            profile_home=home, foreign_keys=True)


def upgrade_plugin_stores(profile_home):
    """Upgrade already-owned portable stores during the explicit Profile database lifecycle."""
    root = Path(profile_home) / 'plugin-data'
    for path in sorted(root.glob('*/portable.db')):
        initialize_plugin_store(path.parent.name, profile_home=profile_home)


def initialize_selected_plugin_stores(profile_home):
    """Explicit Profile lifecycle provisions configured plugins and upgrades owned portable files."""
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.plugins_cmd import _get_enabled_set
    with _owning_profile(profile_home):
        for key in sorted(_get_enabled_set()):
            initialize_plugin_store(key.rsplit('/', 1)[-1], profile_home=profile_home)
        upgrade_plugin_stores(profile_home)


def open_plugin_database(path, *, ready, db_label, profile_home=None, **options):
    """Open a plugin's existing SQLite dataset under its captured application Profile."""
    from hermes_cli.db_sqlite_policy import open_ready_profile_sqlite
    from hermes_constants import get_hermes_home
    home = profile_home if profile_home is not None else get_hermes_home()
    with plugin_profile_scope(home):
        if selected_storage_backend(home) != 'sqlite':
            raise StorageConfigurationError('Selected PostgreSQL plugin storage cannot open SQLite')
        return open_ready_profile_sqlite(path, db_label=db_label, ready=ready, **options)


def initialize_plugin_database(path, *, initialize, db_label, profile_home=None, **options):
    """Run plugin-owned SQLite schema resources only at explicit setup/upgrade."""
    from hermes_cli.db_sqlite_policy import initialize_profile_sqlite
    from hermes_cli.db_sessions import _owner_only
    from hermes_constants import get_hermes_home
    _owner_only()
    home = profile_home if profile_home is not None else get_hermes_home()
    with plugin_profile_scope(home):
        if selected_storage_backend(home) != 'sqlite':
            raise StorageConfigurationError('Selected PostgreSQL plugin storage cannot initialize SQLite')
        def apply_schema(conn):
            with plugin_sqlite_transaction(conn):
                initialize(conn)
        initialize_profile_sqlite(path, db_label=db_label, initialize=apply_schema, **options).close()
