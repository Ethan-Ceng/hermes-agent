"""Application-owned SQLite configuration, install hints and explicit lifecycle composition."""
from __future__ import annotations

import sqlite3
import sys
import time

from hermes_db.infra.backends.sqlite import connections, wal
from hermes_db.infra.backends.sqlite.schema import initialize_database

def resolve_journal_mode() -> str:
    """The configured ``database.journal_mode`` (``wal`` default; ``delete`` for filesystems without WAL-safe
    durability: macOS virtiofs, NFS, SMB). Invalid values fail safe to ``wal``."""
    try:
        from hermes_cli.config import load_config_readonly
        database = (load_config_readonly() or {}).get("database", {})
        raw = database.get("journal_mode", "wal") if isinstance(database, dict) else "wal"
    except Exception:
        return "wal"
    mode = raw.strip().lower() if isinstance(raw, str) else ""
    return mode if mode in ("wal", "delete") else "wal"



def _wal_reset_repair_hint() -> str:
    """Repair hint matching what ``hermes update`` can actually do for this install type.

    See #75153.
    """
    try:
        from hermes_cli.config import detect_install_method, get_project_root, recommended_update_command_for_method
        method = detect_install_method(get_project_root())
        cmd = recommended_update_command_for_method(method)
        if method in {"git", "unknown"}:
            return f"Hermes-managed installs can repair the embedded runtime with `{cmd}`"
        return f"update the container image with `{cmd}`" if method == "docker" else cmd  # else nix/nixos
    except Exception:
        return "install a Python build bundled with SQLite 3.51.3+ (or backports 3.50.7 / 3.44.6) and restart Hermes"



def _repair_hint(db_label):
    # The mechanism deduplicates warnings; avoid repeated application probes after the first one.
    return ("upgrade the linked SQLite runtime" if db_label in wal._wal_reset_bug_warned_paths
            else _wal_reset_repair_hint())


def apply_wal_with_fallback(conn, *, db_label="state.db", require_wal=False):
    """Resolve Profile policy without waiting behind a config writer on an initialized DB."""
    config_module = sys.modules.get("hermes_cli.config")
    if getattr(getattr(config_module, "__spec__", None), "_initializing", False):
        config_module = None
    config_lock = getattr(config_module, "_CONFIG_LOCK", None)
    acquired = config_lock is not None and config_lock.acquire(blocking=False)
    try:
        if config_lock is not None and not acquired:
            current_mode = wal._on_disk_journal_mode(conn)
            if current_mode == "wal":
                if wal.is_sqlite_wal_reset_vulnerable():
                    return wal._apply_delete_for_wal_reset_bug(conn, db_label=db_label, repair_hint=_repair_hint(db_label))
                wal._apply_wal_companions(conn)
                return "wal"
            if current_mode == "delete" and not require_wal and wal._database_has_content(conn):
                if wal.is_sqlite_wal_reset_vulnerable():
                    wal._log_wal_reset_bug_once(db_label, kept_wal=False, repair_hint=_repair_hint(db_label))
                return "delete"
        configured = resolve_journal_mode()
    finally:
        if acquired:
            config_lock.release()
    return wal.apply_wal_with_fallback(conn, db_label=db_label, require_wal=require_wal,
                                      journal_mode=configured, repair_hint=_repair_hint(db_label))


def capture_database_pragmas():
    """Capture the current Profile's optional connection settings as explicit technical values."""
    try:
        from hermes_cli.config import cfg_get, load_config_readonly
        cfg = load_config_readonly()
    except Exception:  # health: allow BLE001 -- Preserve optional tuning best-effort boundary; DB open, DDL and transactions are outside this catch.
        return {}
    names = ("cache_size", "mmap_size", "temp_store", "wal_autocheckpoint", "journal_size_limit", "synchronous")
    pragmas = {name: cfg_get(cfg, "database", name, default=None) for name in names}
    return pragmas



def apply_database_pragmas(conn, *, db_label="state.db"):
    """Apply optional connection tuning captured in the current owning Profile."""
    wal.apply_database_pragmas(conn, pragmas=capture_database_pragmas(), db_label=db_label)


def open_profile_sqlite(path, *, db_label, busy_timeout_ms=5000, wal=True, foreign_keys=False,
                        synchronous_full=False, row_factory=sqlite3.Row, check_same_thread=True, wal_lock_retries=1):
    """Apply application WAL policy to a technical connection without Schema initialization."""
    conn = connections.open_db(path, db_label=db_label, busy_timeout_ms=busy_timeout_ms, wal=False,
                               row_factory=row_factory, check_same_thread=check_same_thread)
    try:
        if wal:
            for attempt in range(wal_lock_retries):
                try:
                    apply_wal_with_fallback(conn, db_label=db_label)
                    break
                except sqlite3.OperationalError as exc:
                    if str(exc).lower() != "database is locked" or attempt + 1 == wal_lock_retries:
                        raise
                    time.sleep(0.01 * (2**attempt))
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys=ON")
        if synchronous_full:
            conn.execute("PRAGMA synchronous=FULL")
    except BaseException:
        conn.close()
        raise
    return conn


def initialize_profile_sqlite(path, *, initialize, **options):
    """Explicit business creation/upgrade composition; ordinary opens use open_profile_sqlite."""
    return initialize_database(open_profile_sqlite(path, **options), initialize)
