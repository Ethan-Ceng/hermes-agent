"""Per-plugin persistent storage: ``<hermes home>/plugin-data/<name>/``.

Plugins must NOT park state in ``<hermes home>/plugins/<name>/`` (the install dir, deleted by
``remove`` and git-pulled by ``update``). Secrets are deliberately NOT part of this convention —
credential reads go through ``agent.secret_scope`` / ``.env``.
Usage: ``plugin_data_dir("my-plugin") / "state.json"``; ``plugin_db("my-plugin")`` → ``data.db``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from .plugin_storage_types import PluginRecord, PluginStorageConflict, PluginStorageQuotaError, PluginStore

__all__ = ["PluginRecord", "PluginStorageConflict", "PluginStorageQuotaError", "PluginStore", "plugin_data_dir", "plugin_db", "plugin_store"]

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
    from hermes_cli.sqlite_util import open_db

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
