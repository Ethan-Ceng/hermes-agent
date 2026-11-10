"""Per-plugin persistent storage: ``<hermes home>/plugin-data/<name>/``.

Plugins must NOT park state in ``<hermes home>/plugins/<name>/`` (the install dir, deleted by
``remove`` and git-pulled by ``update``). Secrets are deliberately NOT part of this convention —
credential reads go through ``agent.secret_scope`` / ``.env``.
Usage: ``plugin_data_dir("my-plugin") / "state.json"``; ``plugin_db("my-plugin")`` → ``data.db``.
"""

from __future__ import annotations

from contextlib import contextmanager
import re
import sqlite3
from pathlib import Path
from .plugin_storage_types import PluginRecord, PluginStorageConflict, PluginStorageQuotaError, PluginStore

__all__ = ["PluginRecord", "PluginStorageConflict", "PluginStorageQuotaError", "PluginStore", "configure_plugin_sqlite", "plugin_data_dir", "plugin_db", "plugin_sqlite_transaction", "plugin_store", "session_history"]

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
        from hermes_db.domains.plugin_storage.records.postgres.store import PostgresPluginStore
        return PostgresPluginStore(name, namespace, home)
    from hermes_db.backends.sqlite.plugin_storage import SQLitePluginStore
    return SQLitePluginStore(name, namespace, home)


@contextmanager
def plugin_sqlite_transaction(conn):
    """Commit or roll back an explicit legacy SQLite plugin operation without closing its connection."""
    from hermes_db.infra.backends.sqlite.transactions import write_txn
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
