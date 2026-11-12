from __future__ import annotations
import contextlib
import errno
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import stat
from hermes_platform.host.facts import os_family
from hermes_db.infra.sqlite.wal import _on_disk_journal_mode
from hermes_cli.db_sqlite_policy import apply_database_pragmas, apply_wal_with_fallback
from hermes_db.infra.sqlite.generation import canonical_sqlite_path, _iter_proc_fd_targets, _iter_darwin_fd_targets
logger = logging.getLogger("hermes_state")

from hermes_state_common import FTS_REBUILD_DEFERRAL_KEY
from hermes_state_holders import read_only_db_uri
from hermes_db.infra.sqlite.generation import (RetiredGenerationCaptureError, _preopen_header, _pread_db_range, _stat_sqlite_sidecar_identity, stat_db_file_identity as _stat_db_file_identity, _connect_tracked_db)

_FTS_TABLE_NAMES = ("messages_fts", "messages_fts_trigram")


RETIRED_GENERATION_DIR_SUFFIX = ".retired-wal-"


RETIRED_GENERATION_MANIFEST = "manifest.json"


RETIRED_GENERATION_MANIFEST_VERSION = 1


RETIRED_GENERATION_MAIN_IMAGE_MAX_BYTES = 512 * 1024 * 1024


_CAPTURE_CHUNK_BYTES = 8 * 1024 * 1024


_SQLITE_HEADER_BYTES = 100


def _fsync_path(path: Path) -> None:
    """fsync a file or directory we own. Never used on the live database: opening and closing a
    descriptor on a file SQLite has locked would cancel this process's POSIX advisory locks."""
    if os_family() == "win32":
        return  # directories cannot be opened; file writes fsync their own handle
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _own_descriptor_for_identity(identity) -> Optional[int]:
    """This process's open descriptor for the inode ``(st_dev, st_ino)``, or None.

    Exact-generation qualified: pathnames are never consulted. The descriptor stays owned by
    SQLite; callers only pread from it."""
    if not identity:
        return None
    wanted = tuple(identity)
    for fd_dir in ("/proc/self/fd", "/dev/fd"):
        try:
            names = os.listdir(fd_dir)
        except OSError:
            continue
        for name in names:
            if not name.isdigit():
                continue
            try:
                st = os.fstat(int(name))
            except OSError:
                continue
            if (st.st_dev, st.st_ino) == wanted:
                return int(name)
        return None  # the table was readable: a definitive miss
    return None


def _copy_range(read: Callable[[int, int], Optional[bytes]], dest: Path, *, size: int) -> dict[str, Any]:
    """Stream ``size`` bytes via ``read(offset, length)`` into ``dest`` (temp file, fsync, rename).

    A short read raises ``RetiredGenerationCaptureError``: a truncated copy with a valid-looking
    manifest would let the caller settle the handle while the unlinked inode still dies at exit."""
    digest = hashlib.sha256()
    part = dest.with_name(dest.name + ".part")
    offset = 0
    try:
        with open(part, "wb") as out:
            while offset < size:
                chunk = read(offset, min(_CAPTURE_CHUNK_BYTES, size - offset))
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                offset += len(chunk)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if offset != size:
        part.unlink(missing_ok=True)
        raise RetiredGenerationCaptureError(
            f"short read copying {dest.name}: {offset} of {size} bytes — the retired generation "
            "is NOT fully captured; the handle stays open for a retry"
        )
    os.replace(part, dest)
    return {"file": dest.name, "bytes": offset, "sha256": digest.hexdigest()}


def _copy_descriptor(fd: int, dest: Path, *, size: int) -> dict[str, Any]:
    """pread ``fd`` (a descriptor SQLite owns; never closed here) into ``dest``."""
    return _copy_range(lambda offset, length: os.pread(fd, length, offset), dest, size=size)


def _copy_main_image(db_path: Path, dest: Path, *, size: int) -> dict[str, Any]:
    """Copy the live main file through the lock-safe cached descriptor (see ``_pread_db_range``)."""
    return _copy_range(lambda offset, length: _pread_db_range(db_path, offset, length), dest, size=size)


def _parse_sqlite_header(header: bytes) -> dict[str, Any]:
    if len(header) < _SQLITE_HEADER_BYTES or header[:16] != b"SQLite format 3\x00":
        return {"valid": False}
    raw_page_size = struct.unpack(">H", header[16:18])[0]
    from hermes_db.infra.sqlite.generation import _STATE_DB_APPLICATION_ID_OFFSET
    fields = {"change_counter": 24, "page_count": 28, "user_version": 60,
              "application_id": _STATE_DB_APPLICATION_ID_OFFSET, "version_valid_for": 92}
    parsed = {name: struct.unpack(">I", header[off:off + 4])[0] for name, off in fields.items()}
    return {"valid": True, "page_size": 65536 if raw_page_size == 1 else raw_page_size, **parsed}


def capture_retired_wal_generation(
    db_path, *, sidecar_identity: dict[str, tuple], trigger: str,
) -> Path:
    """Durably capture the lost WAL generation this process still holds open; return the artifact dir.

    The artifact sits next to the database as ``<name>.retired-wal-<utc ts>-<pid>/`` and holds the
    retired ``<name>-wal`` (and ``-shm`` when still ours), the main image (or its header past the size
    cap) and ``manifest.json`` with identities, sizes, digests and the sidecar generation found at the
    path at capture time. Nothing is merged: whether those frames belong on top of the main file is
    the operator's decision. Raises :class:`RetiredGenerationCaptureError` when the exact generation
    cannot be located or written; no descriptor is ever closed, moved or truncated.
    """
    db_path = Path(db_path)
    wal_identity = tuple(sidecar_identity.get("-wal") or ())
    if not wal_identity:
        raise RetiredGenerationCaptureError(
            f"no recorded WAL generation identity for {db_path}; refusing to guess it by pathname")
    wal_fd = _own_descriptor_for_identity(wal_identity)
    if wal_fd is None:
        raise RetiredGenerationCaptureError(
            f"this process no longer holds the retired WAL inode {wal_identity} of {db_path}")
    try:
        wal_size = os.fstat(wal_fd).st_size
    except OSError as exc:
        raise RetiredGenerationCaptureError(f"cannot stat the retired WAL of {db_path}: {exc}") from exc

    stem = f"{db_path.name}{RETIRED_GENERATION_DIR_SUFFIX}{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{os.getpid()}"
    final = db_path.with_name(stem)
    n = 0
    while final.exists() or final.with_name(final.name + ".partial").exists():
        n += 1
        final = db_path.with_name(f"{stem}-{n}")
    staging = final.with_name(final.name + ".partial")
    try:
        staging.mkdir(parents=True, exist_ok=False)
        manifest: dict[str, Any] = {
            "version": RETIRED_GENERATION_MANIFEST_VERSION,
            "database": str(db_path),
            "trigger": trigger,
            "pid": os.getpid(),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
            "wal": {"identity": list(wal_identity),
                    **_copy_descriptor(wal_fd, staging / (db_path.name + "-wal"), size=wal_size)},
            "shm": None,
            # The generation living at the path when we captured: a newer writer's, if one was minted.
            "path_generation_at_capture": {
                suffix: list(ident) for suffix, ident in _stat_sqlite_sidecar_identity(db_path).items()},
            "note": ("Frames in the captured WAL were committed by the retired generation. Whether they "
                     "belong on top of the main file now at the path is an operator decision; inspect "
                     "the copied image with `hermes sessions recover --inspect-only` first."),
        }
        shm_identity = tuple(sidecar_identity.get("-shm") or ())
        shm_fd = _own_descriptor_for_identity(shm_identity) if shm_identity else None
        if shm_fd is not None:
            with contextlib.suppress(OSError):  # SQLite rebuilds the index; the WAL is what matters
                manifest["shm"] = {"identity": list(shm_identity), **_copy_descriptor(
                    shm_fd, staging / (db_path.name + "-shm"), size=os.fstat(shm_fd).st_size)}
        header = _pread_db_range(db_path, 0, _SQLITE_HEADER_BYTES)
        if header is None:
            raise RetiredGenerationCaptureError(f"cannot read the main image header of {db_path}")
        main_size = os.stat(db_path).st_size
        main: dict[str, Any] = {"identity": list(_stat_db_file_identity(db_path) or ()) or None,
                                "size": main_size, "header": _parse_sqlite_header(header)}
        if main_size <= RETIRED_GENERATION_MAIN_IMAGE_MAX_BYTES:
            main.update(mode="copied", **_copy_main_image(db_path, staging / db_path.name, size=main_size))
        else:
            header_file = staging / (db_path.name + ".header")
            header_file.write_bytes(header)
            _fsync_path(header_file)
            main.update(mode="header_only", file=header_file.name, bytes=len(header))
        manifest["main"] = main
        # Late import: utils pulls agent-side deps; the capture must stay dependency-light.
        from utils import atomic_json_write
        atomic_json_write(staging / RETIRED_GENERATION_MANIFEST, manifest, sort_keys=True)
        _fsync_path(staging)
        os.replace(staging, final)
        _fsync_path(final.parent)
    except RetiredGenerationCaptureError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RetiredGenerationCaptureError(
            f"could not write the retired WAL generation of {db_path} under {staging}: {exc}") from exc
    return final


def is_zeroed_state_db(path: Path, *, probe_bytes: int = 100, force: bool = False) -> bool:
    """Detect the zeroed state.db signature (0-byte or NUL header).  Prefers
    ``hermes_cli.backup.is_zeroed_sqlite_file``; this copy keeps SessionDB openable without the CLI
    package in constrained embed paths."""
    with contextlib.suppress(Exception):
        from hermes_cli.backup import is_zeroed_sqlite_file
        return is_zeroed_sqlite_file(path, probe_bytes=probe_bytes, force=force)
    head = _preopen_header(path, probe_bytes, force)
    # b"" (0-byte file) is zeroed; all() over an empty header is True.
    return head is not None and not head.startswith(b"SQLite format 3") and all(b == 0 for b in head)


def has_invalid_sqlite_header_preopen(path: Path, *, probe_bytes: int = 100, force: bool = False) -> bool:
    """A pre-existing state.db whose first page is not SQLite: 0-byte, NUL, or clobbered page 0
    (#102198).  Zeroed files are the subset :func:`is_zeroed_state_db` names."""
    head = _preopen_header(path, probe_bytes, force)
    return head is not None and not head.startswith(b"SQLite format 3")


@contextlib.contextmanager
def quarantine_cross_process_lock(path: Path, timeout: float = 5.0):
    """Acquire the cross-process lock for path.quarantine.lock."""
    lock_path = path.with_name(path.name + ".quarantine.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        if os_family() == "win32":
            import msvcrt
            def _lock(mode):  # msvcrt locks a byte range from the current position
                handle.seek(0)
                msvcrt.locking(handle.fileno(), mode, 1)

            _try_lock = lambda: _lock(msvcrt.LK_NBLCK)
            _unlock = lambda: _lock(msvcrt.LK_UNLCK)
        else:
            import fcntl
            _try_lock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            _unlock = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + timeout
        while not acquired:
            try:
                _try_lock()
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.020)
        yield acquired
    finally:
        try:
            if acquired:
                _unlock()
        except (OSError, AttributeError):
            pass
        finally:
            handle.close()


def quarantine_invalid_state_db(path: Path, *, already_locked: bool = False) -> Optional[Path]:
    """Move a non-SQLite state.db (zeroed or clobbered page 0) aside with its -wal/-shm sidecars,
    preserving bytes; return the quarantine path.  A cross-process lock stops two concurrent
    startups racing: the second re-checks under the lock and finds the file gone (or fresh)."""
    def _do_quarantine():
        if not path.exists():
            logger.info("quarantine_invalid_state_db: %s already moved by another process", path)
            return None
        if not has_invalid_sqlite_header_preopen(path):
            logger.info("quarantine_invalid_state_db: %s is no longer invalid (another "
                        "process quarantined it and a fresh DB was created)", path)
            return None
        kind = "zeroed" if is_zeroed_state_db(path) else "notadb"
        try:
            ts = time.strftime("%Y%m%d-%H%M%S")
        except Exception:
            ts = "unknown"
        stem = f"{path.name}.{kind}-{ts}-{os.getpid()}"
        dest = path.with_name(f"{stem}.bak")
        n = 0
        while dest.exists():
            n += 1
            dest = path.with_name(f"{stem}-{n}.bak")
        try:
            path.rename(dest)
        except OSError as exc:
            logger.error("Failed to quarantine invalid %s: %s", path, exc)
            return None
        for suffix in ("-wal", "-shm"):
            side = Path(str(path) + suffix)
            if side.exists():
                with contextlib.suppress(OSError):
                    side.rename(Path(str(dest) + suffix))
        return dest

    if already_locked:
        return _do_quarantine()
    with quarantine_cross_process_lock(path) as acquired:
        if not acquired:
            logger.error("quarantine lock for %s not acquired within 5s — refusing to "
                         "quarantine without the cross-process lock. The invalid file "
                         "is left in place. If sessions fail to load, run `hermes sessions recover "
                         "--source <state.db> --inspect-only`, or restore a snapshot with "
                         "`/snapshot list` / `/snapshot restore <id>` (terminal `hermes` chat only).",
                         path)
            return None
        return _do_quarantine()


def collect_state_db_stats(db_path: Path) -> dict[str, Any]:
    """Best-effort, strictly read-only stats snapshot of a state.db file: ``mode=ro`` with a short
    timeout so it can run against a *live* database without taking a write lock.  Every field is
    collected independently (a failed pragma/SELECT yields ``None`` for it); never raises.
    Deliberately does NOT instantiate :class:`SessionDB` — its constructor runs DDL.
    ``wal_size_bytes`` is 0 when the sidecar is absent; ``fts_storage_version`` None means the
    legacy inline layout; ``fts_rebuild_deferral`` is the durable blocked-repair diagnostic."""
    stats: dict[str, Any] = dict.fromkeys((
        "page_count", "page_size", "freelist_count", "logical_size_bytes", "wal_size_bytes", "journal_mode",
        "messages", "sessions", "fts_tables", "fts_storage_version", "fts_storage_upgrade_needed",
        "fts_teardown_pending", "fts_rebuild_pending",
        "fts_rebuild_high_water", "fts_rebuild_progress", "fts_rebuild_deferral"))
    # WAL sidecar size needs no connection at all.
    with contextlib.suppress(OSError):
        wal_path = Path(str(db_path) + "-wal")
        stats["wal_size_bytes"] = wal_path.stat().st_size if wal_path.exists() else 0
    try:
        # A short timeout keeps doctor snappy when a writer holds the lock.  The tracked connect
        # lets byte-probe helpers see this connection and refuse raw opens that would cancel locks.
        conn = _connect_tracked_db(read_only_db_uri(db_path), tracking_path=Path(db_path),
                                   uri=True, timeout=2.0)
    except Exception as exc:
        logger.debug("collect_state_db_stats: cannot open %s read-only: %s", db_path, exc)
        return stats
    def _scalar(sql: str, params=()) -> Any:
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None
        except Exception:
            return None
    def _int(sql: str, params=()) -> Optional[int]:
        value = _scalar(sql, params)
        return int(value) if value is not None else None
    def _meta_int(key: str) -> Optional[int]:
        try:  # a non-numeric meta value must yield None, not fail the snapshot
            return _int("SELECT value FROM state_meta WHERE key = ?", (key,))
        except Exception:
            return None

    try:
        stats["page_count"] = _int("PRAGMA page_count")
        stats["page_size"] = _int("PRAGMA page_size")
        if stats["page_count"] is not None and stats["page_size"] is not None:
            stats["logical_size_bytes"] = stats["page_count"] * stats["page_size"]
        stats["freelist_count"] = _int("PRAGMA freelist_count")
        jm = _scalar("PRAGMA journal_mode")
        stats["journal_mode"] = str(jm) if jm is not None else None
        stats["messages"] = _int("SELECT COUNT(*) FROM messages")
        stats["sessions"] = _int("SELECT COUNT(*) FROM sessions")
        # FTS table presence via sqlite_master (never SELECTs from the
        # virtual tables themselves — a corrupt index must not fail stats).
        with contextlib.suppress(Exception):
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?)",
                _FTS_TABLE_NAMES).fetchall()}
            stats["fts_tables"] = {t: (t in names) for t in _FTS_TABLE_NAMES}
        # Raw state_meta reads — cheap, and independent of SessionDB.
        stats["fts_storage_version"] = _meta_int("fts_storage_version")
        with contextlib.suppress(Exception):
            from hermes_state_fts import fts_layout_drift
            stats["fts_storage_upgrade_needed"] = bool(fts_layout_drift(conn.cursor()))
        with contextlib.suppress(Exception):
            # Demoted old-index tables still awaiting teardown: an optimize-storage run stopped after its backfill.
            stats["fts_teardown_pending"] = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name LIKE 'fts\\_v22\\_trash\\_%' ESCAPE '\\' "
                "LIMIT 1").fetchone() is not None
        stats["fts_rebuild_high_water"] = high_water = _meta_int("fts_rebuild_high_water")
        stats["fts_rebuild_progress"] = progress = _meta_int("fts_rebuild_progress")
        stats["fts_rebuild_pending"] = False if high_water is None else (progress or 0) < high_water
        with contextlib.suppress(Exception):
            row = conn.execute("SELECT value FROM state_meta WHERE key = ? LIMIT 1",
                               (FTS_REBUILD_DEFERRAL_KEY,)).fetchone()
            parsed = json.loads(row[0]) if row else None
            if isinstance(parsed, dict):
                stats["fts_rebuild_deferral"] = parsed
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    return stats


def count_db_holders(db_path: Path) -> Optional[int]:
    """Best-effort count of distinct PIDs holding ``db_path`` open (``/proc/*/fd`` on Linux, libproc
    on macOS); ``None`` on any error or other host, never raises.  Uninspectable processes (other
    users' without root) are skipped, so this is a lower bound."""
    try:
        target = os.path.realpath(str(db_path))
        if sys.platform == "darwin":
            # Identity, not pathname: libproc reports the vnode's last name as the opener spelled it
            # (case, symlinked prefix), which is exactly what the sidecar leg had to case-fold around.
            st = os.stat(target)
            identity = (st.st_dev, st.st_ino)
            return len({pid for pid, _fd, _path, ident in _iter_darwin_fd_targets() if ident == identity})
        if not sys.platform.startswith("linux"):
            return None
        return len({pid for pid, link, _fd_path in _iter_proc_fd_targets() if link == target})
    except Exception:
        return None


def _is_inactive_orphan_desktop_holder(*, ppid: int, age_seconds: float, min_age_seconds: float,
                                       ephemeral_backend: bool, connection_statuses: list[str]) -> bool:
    """Pure safety predicate for the narrow Desktop holder reap."""
    return (ppid in (0, 1) and age_seconds >= min_age_seconds and ephemeral_backend
            and "ESTABLISHED" not in connection_statuses)


def _concrete_state_db_holder_pids(db_path: Path, holders: list[tuple[int, str]]) -> list[int]:
    """Return unique PIDs proven to hold this DB or one of its sidecars."""
    canonical_db = os.path.normcase(os.path.abspath(os.fspath(db_path)))
    watched = {canonical_db, canonical_db + "-wal", canonical_db + "-shm"}
    return list(dict.fromkeys(
        pid for pid, path in holders if pid > 0 and canonical_sqlite_path(path) in watched))



def _secure_state_db_files(db_path: Path, *, create_main: bool = False) -> None:
    """Create/tighten a writable state database and its sidecars to 0600.

    SQLite otherwise creates ``state.db``, ``-wal``, and ``-shm`` according to
    the process umask (commonly 0644 under 0022). Read-only SessionDB
    attachments never call this helper and remain observational.

    Existing files are tightened with ``chmod(2)`` on the path: opening the
    file and closing that descriptor would drop every POSIX ``fcntl`` lock the
    process holds on its inode — including the locks of an already-open SQLite
    connection to the same database. A lock-losing close in one process lets a
    sibling's connection take the shared-memory DMS exclusively at its own
    close, checkpoint, and unlink the sidecars while long-lived holders
    (gateway, desktop ``hermes serve``) keep using the deleted inodes.
    """
    if os.name == "nt":
        return

    main_path = db_path
    if create_main:
        # O_EXCL: only a brand-new inode gets a descriptor. Opening an existing
        # file here and closing it would drop this process's POSIX locks on it.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            fd = os.open(main_path, flags, 0o600)
        except FileExistsError:
            pass
        except IsADirectoryError:
            # Not a database file at all; sqlite3.connect() raises the
            # canonical error for this, and a directory leaks no row data.
            return
        else:
            os.close(fd)

    for path in (
        main_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ):
        # fchmod on an fd of a pre-existing file cannot be used here: close(fd)
        # would release this process's POSIX locks on that inode, stripping the
        # locks of any live SQLite connection to the same database. chmod(2)
        # never opens the file, so it leaves the lock state untouched.
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            # Refuse a planted symlink exactly like O_NOFOLLOW would.
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        os.chmod(path, 0o600)


def open_session_writer(resource) -> sqlite3.Connection:
    """Connect + WAL/pragma setup for a writer connection (no schema init). Short timeout:
    jittered application-level retry handles contention, not SQLite's busy handler;
    isolation_level=None: explicit BEGIN IMMEDIATE."""
    conn = resource.connect_writer()
    try:
        configure_session_writer(resource, conn)
    except BaseException:
        resource._close_connection_quietly(conn)
        raise
    return conn


def configure_session_writer(resource, conn) -> None:
    """Configure an already-open writer after any readiness probe."""
    conn.row_factory = sqlite3.Row
    mode = apply_wal_with_fallback(conn, db_label="state.db")
    # "wal" is also the *assumed* mode when the on-disk probe was blocked by a concurrent opener
    # (#86515): the lock-free mode=ro read pool needs a confirmed WAL header, so confirm it here.
    # Unknown -> reads queue on the writer lock (slow but correct) instead of racing SQLITE_BUSY
    # on a file that may really be in rollback-journal mode.
    resource._wal_active = mode == "wal" and _on_disk_journal_mode(conn) == "wal"
    # Existing WAL/SHM files may predate the main-file hardening;
    # normalize any sidecars that became visible during WAL setup.
    _secure_state_db_files(resource.db_path)
    apply_database_pragmas(conn, db_label="state.db")
    conn.execute("PRAGMA foreign_keys=ON")


def initialize_new_profile_sessions(profile_home: Path) -> None:
    """Seed only the missing SQLite dataset during an explicit Profile setup."""
    from hermes_cli.db_scope import bind_profile_home
    from hermes_cli.db_sessions import _owner_only
    from hermes_cli.db_setup import storage_backend
    from hermes_db.scope import DatabaseScope
    from hermes_state import SessionDB

    _owner_only()
    path = profile_home / "state.db"
    if not path.exists() and storage_backend(profile_home) == "sqlite":
        with bind_profile_home(DatabaseScope(profile_home)), SessionDB(path):
            pass


def sqlite_session_schema_status(scope) -> dict:
    from hermes_cli.db_scope import bind_profile_home
    from hermes_db.errors import StorageSchemaError
    from hermes_state import SessionDB
    from hermes_state_common import SCHEMA_VERSION

    result = {"backend": "sqlite", "profile_home": str(scope.profile_home),
              "required_revision": SCHEMA_VERSION, "ready": False}
    try:
        with bind_profile_home(scope), SessionDB.open_existing(scope.profile_home / "state.db", read_only=True):
            result.update(ready=True, revision=SCHEMA_VERSION)
    except StorageSchemaError as exc:
        result["detail"] = str(exc)
    except (sqlite3.DatabaseError, UnicodeDecodeError):
        result["detail"] = "Session store is unavailable. Run `hermes doctor` for this profile."
    return result


def upgrade_sqlite_session_schema(scope) -> dict:
    from gateway.runtime_ownership import OwnershipConflict, exclusive_maintenance
    from hermes_cli.db_scope import bind_profile_home
    from hermes_db.errors import StorageSchemaError
    from hermes_state import SessionDB
    from hermes_state_reconcile import DeclarativeDriftError, reconcile_declarative_drift

    path = scope.profile_home / "state.db"
    try:
        with bind_profile_home(scope):
            if path.exists():
                _check_sqlite_upgrade_source(path)
                reconcile_declarative_drift(path)
            with exclusive_maintenance([scope.profile_home], purpose="db_upgrade"):
                if path.exists():
                    _check_sqlite_upgrade_source(path)
                with SessionDB(path):
                    pass
                return sqlite_session_schema_status(scope)
    except DeclarativeDriftError as exc:
        raise StorageSchemaError(str(exc)) from None
    except OwnershipConflict:
        raise StorageSchemaError("Stop this profile's gateway before running `hermes db upgrade`.") from None
    except (sqlite3.DatabaseError, UnicodeDecodeError):
        raise StorageSchemaError("Could not upgrade the session store. Run `hermes doctor` for this profile.") from None


def _check_sqlite_upgrade_source(path: Path) -> None:
    """Refuse an incompatible image before a legacy constructor could change it."""
    from contextlib import closing

    from hermes_db.errors import StorageSchemaError
    from hermes_db.infra.sqlite.safe_read import connect_tracked
    from hermes_state_common import SCHEMA_VERSION
    from hermes_state_reconcile import _require_history_tables

    with closing(connect_tracked(path.resolve().as_uri() + "?mode=ro", uri=True, tracking_path=path)) as conn:
        try:
            _require_history_tables(conn)
        except RuntimeError:
            raise StorageSchemaError(
                "Session store history tables are missing. Run `hermes sessions recover` "
                "or `hermes doctor` for this profile."
            ) from None
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone():
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row and isinstance(row[0], int) and row[0] > SCHEMA_VERSION:
                raise StorageSchemaError("Session store schema is newer than this Hermes release.")
