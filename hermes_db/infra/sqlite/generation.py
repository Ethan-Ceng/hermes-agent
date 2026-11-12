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
from hermes_platform.host.facts import os_family
from hermes_db.infra.sqlite.lockguard import own_descriptors
logger = logging.getLogger("hermes_state")

class StateDbReplacedError(RuntimeError):
    """The state.db path no longer names the file this SessionDB opened
    (out-of-band cp/mv/restore). In-place FTS repair and fail-open trigger
    dropping cannot fix a generation mismatch; they amplify it."""


class DeletedWalGenerationError(StateDbReplacedError):
    """A live process holds a deleted state.db-wal / -shm generation. Opening or
    writing through this handle would mint a second WAL inode (split-brain ->
    intermittent SQLITE_CORRUPT / IOERR). Stop the writers; never unlink the WAL
    yourself. Subclasses StateDbReplacedError so every consumer that diverts
    transcripts on a replaced store handles this identically."""


def stat_db_file_identity(path) -> tuple[int, int] | None:
    """``(st_dev, st_ino)`` for *path*, or None.  st_ino=0 (Windows, some network FS) would false-positive
    every replaced-file check, so it counts as unknown."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if st.st_dev and st.st_ino else None


def canonical_sqlite_path(path: str) -> str:
    """Normalize a /proc fd target, stripping the Linux `` (deleted)`` suffix."""
    return os.path.normcase(os.path.abspath(path.removesuffix(" (deleted)")))


def _prepare_connection_retirement():
    """Bind a non-finalizing reference before opening a writable SQLite handle.

    A Python container is cleared during interpreter shutdown. An unmatched
    CPython C reference keeps the exact connection alive through that cleanup,
    so SQLite cannot checkpoint its lost WAL generation from a finalizer. This
    deliberately retains the connection and its descriptors until process exit;
    it does not make already-unlinked WAL data durable after the last fd closes.
    """
    message = (
        "Writable SessionDB on a Python without sqlite3 setconfig (< 3.12) requires CPython with "
        "ctypes support to retain a quarantined SQLite connection through interpreter shutdown."
    )
    if sys.implementation.name != "cpython":
        raise RuntimeError(message)
    try:
        import ctypes

        # A private function object avoids changing another caller's signature.
        retain = ctypes.pythonapi["Py_IncRef"]
        retain.argtypes = (ctypes.py_object,)
        retain.restype = None
    except (ImportError, AttributeError, OSError) as exc:
        raise RuntimeError(message) from exc
    return retain


_HEADER_PROBE_LOCK = threading.Lock()
_HEADER_PROBE_LOCK_TIMEOUT = 0.1


_HEADER_PROBE_FDS: dict[str, tuple[int, int, int]] = {}  # key -> (fd, dev, ino)


_RETIRED_HEADER_PROBE_FDS: list[int] = []  # intentionally never closed


def _pread_db_range(db_path: Path, offset: int, length: int) -> Optional[bytes]:
    """Lock-safe raw read of a possibly-live SQLite database: POSIX preads from a cached,
    never-closed fd (rebound when the path names a new inode); Windows reads plainly, since
    advisory-lock cancellation is a POSIX-only hazard."""
    if os_family() == "win32":
        with contextlib.suppress(OSError), db_path.open("rb") as handle:
            handle.seek(offset)
            return handle.read(length)
        return None
    key = str(db_path)
    try:
        st = os.stat(db_path)
    except OSError:
        return None
    with _HEADER_PROBE_LOCK:
        cached = _HEADER_PROBE_FDS.get(key)
        if cached is not None and (cached[1], cached[2]) != (st.st_dev, st.st_ino):
            # Path re-pointed at a new file. Retire (never close) the old fd.
            _RETIRED_HEADER_PROBE_FDS.append(_HEADER_PROBE_FDS.pop(key)[0])
            cached = None
        if cached is None:
            try:
                fd = os.open(db_path, os.O_RDONLY)
            except OSError:
                return None
            try:
                fst = os.fstat(fd)
            except OSError:
                _RETIRED_HEADER_PROBE_FDS.append(fd)
                return None
            cached = _HEADER_PROBE_FDS[key] = (fd, fst.st_dev, fst.st_ino)
        with contextlib.suppress(OSError):
            return os.pread(cached[0], length, offset)
    return None


def _pread_db_header(db_path: Path, length: int) -> Optional[bytes]:
    """Lock-safe raw header read of a possibly-live SQLite database (see :func:`_pread_db_range`)."""
    return _pread_db_range(db_path, 0, length)


_STATE_DB_APPLICATION_ID_OFFSET = 68


def _read_sqlite_application_id(db_path: Path) -> Optional[int]:
    """application_id from the SQLite header, via the lock-safe :func:`_pread_db_header`."""
    end = _STATE_DB_APPLICATION_ID_OFFSET + 4
    header = _pread_db_header(db_path, end)
    if header is None or len(header) < end or header[:16] != b"SQLite format 3\x00":
        return None
    return int(struct.unpack(">I", header[_STATE_DB_APPLICATION_ID_OFFSET:end])[0])


def _stat_sqlite_sidecar_identity(db_path: Path) -> dict[str, tuple]:
    """Snapshot ``(st_dev, st_ino)`` for existing WAL/SHM sidecars."""
    base = os.fspath(db_path)
    idents = {suffix: stat_db_file_identity(Path(base + suffix)) for suffix in ("-wal", "-shm")}
    return {suffix: ident for suffix, ident in idents.items() if ident is not None}


def _watched_sqlite_sidecar_paths(db_path) -> dict[str, str]:
    """Map each sidecar's canonical (/proc-comparable) form to its literal, still-named path,
    so a canonical match can be re-``stat``'d for identity rather than trusted as text."""
    literal_base = os.path.abspath(os.fspath(db_path))
    literal = (literal_base + "-wal", literal_base + "-shm")
    watched = {canonical_sqlite_path(path): path for path in literal}
    # /proc reports the kernel-resolved dentry, so the watched canonicals must also resolve
    # symlinks -- with abspath alone a symlinked HERMES_HOME makes every deleted sidecar
    # invisible to the scan. Both spellings are watched: the fully resolved path, which is
    # where current SQLite places -wal/-shm when the database file itself is a symlink, and
    # the realpath'd parent with the literal basename, which is where they land when SQLite
    # names the sidecars after the path it was opened through.
    resolved_bases = (
        os.path.join(os.path.realpath(os.path.dirname(literal_base)),
                     os.path.basename(literal_base)),
        os.path.realpath(literal_base),
    )
    for base in resolved_bases:
        for suffix in ("-wal", "-shm"):
            watched.setdefault(canonical_sqlite_path(base + suffix), base + suffix)
    return watched


def _identity_is_truly_unlinked(identity: tuple[int, int], watched_path: str) -> bool:
    """The shared verdict: does ``(st_dev, st_ino)`` name a generation the watched path no longer
    holds?  See :func:`_fd_is_truly_unlinked` for why the test is identity and never link count."""
    try:
        watched_stat = os.stat(watched_path)
    except OSError:
        return True
    return identity != (watched_stat.st_dev, watched_stat.st_ino)


def _fd_is_truly_unlinked(fd_path: str, watched_path: str) -> bool:
    """Confirm a `` (deleted)`` /proc fd target really names an orphaned generation, not the
    CURRENT watched sidecar.

    The suffix alone is not proof: on OpenZFS a live, still-linked file whose dentry was
    unhashed is reported as deleted while it is still the very same inode the watched path
    names. Conversely ``st_nlink == 0`` is not proof of the opposite — a stale generation can
    keep a surviving hard link (a backup, an operator copy) after the watched path itself is
    removed or replaced, leaving ``st_nlink >= 1`` on a truly orphaned inode. So compare
    identity, not link count: only an exact ``(st_dev, st_ino)`` match between the fd and the
    CURRENT watched path proves they are the same live file. A mismatch, or a watched path
    that cannot be stat'd at all, means the fd holds a generation the watched path no longer
    names — the guard keeps failing closed."""
    try:
        fd_stat = os.stat(fd_path)
    except OSError as exc:
        # ENOENT: the descriptor was closed after /proc was read. ESRCH: the whole
        # process exited mid-scan. Neither can keep a retired generation alive, so
        # do not turn this scan race into a refusal (mirrors hermes_state_holders).
        if exc.errno in (errno.ENOENT, errno.ESRCH):
            return False
        return True
    return _identity_is_truly_unlinked((fd_stat.st_dev, fd_stat.st_ino), watched_path)


def _iter_proc_fd_targets():
    """Yield ``(pid, readlink target, fd path)`` for every readable ``/proc/<pid>/fd`` entry."""
    for pid_str in os.listdir("/proc"):
        if not pid_str.isdigit():
            continue
        fd_dir = f"/proc/{pid_str}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue  # process gone or not ours
        for fd in fds:
            with contextlib.suppress(OSError):
                fd_path = f"{fd_dir}/{fd}"
                yield int(pid_str), os.readlink(fd_path), fd_path


_DARWIN_ALL_PIDS = 1


_DARWIN_PIDLISTFDS = 1


_DARWIN_PIDFDVNODEPATHINFO = 2


_DARWIN_PROC_FD_INFO_SIZE = 8  # struct proc_fdinfo { int32 proc_fd; uint32 proc_fdtype; }


_DARWIN_FD_RECORD_SIZE = 1200  # PROC_PIDFDVNODEPATHINFO_SIZE


_DARWIN_FD_DEV_OFFSET = 24


_DARWIN_FD_INO_OFFSET = 32


_DARWIN_FD_PATH_OFFSET = 176


_DARWIN_LIBPROC = None


_DARWIN_FD_SCAN_TIMEOUT_SECONDS = 5.0


def _darwin_libproc():
    """libproc's fd-enumeration entry points, loaded once per process.

    macOS exports these from libSystem, so this process's own handle resolves them; a failure
    here propagates to the caller's ``except Exception`` and keeps the guard fail-open."""
    global _DARWIN_LIBPROC
    lib = _DARWIN_LIBPROC
    if lib is not None:
        return lib
    import ctypes

    lib = ctypes.CDLL(None, use_errno=True)
    lib.proc_listpids.restype = ctypes.c_int
    lib.proc_listpids.argtypes = (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32)
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int)
    lib.proc_pidfdinfo.restype = ctypes.c_int
    lib.proc_pidfdinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
    _DARWIN_LIBPROC = lib
    return lib


def _darwin_all_pids(lib) -> list[int]:
    """Every pid ``proc_listpids`` will name (the kernel silently omits ones we may not inspect)."""
    import ctypes

    size = 4096 * 8
    while True:
        buffer = ctypes.create_string_buffer(size)
        used = lib.proc_listpids(_DARWIN_ALL_PIDS, 0, buffer, size)
        if used <= 0:
            return []
        if used < size:
            return [pid for pid in struct.unpack_from(f"<{used // 4}i", buffer.raw) if pid > 0]
        size *= 2


def _iter_darwin_fd_targets():
    """Yield ``(pid, fd, last pathname, (st_dev, st_ino))`` for every vnode fd libproc reports.

    The pathname and the identity both stay readable after the path is unlinked, which is what
    makes an orphaned WAL generation visible at all on macOS.  Processes that cannot be inspected
    (gone, or not ours) and descriptors that are not vnodes are skipped silently."""
    import ctypes

    lib = _darwin_libproc()
    for pid in _darwin_all_pids(lib):
        size = 4096
        while True:
            listing = ctypes.create_string_buffer(size)
            used = lib.proc_pidinfo(pid, _DARWIN_PIDLISTFDS, 0, listing, size)
            if used <= 0:
                break  # process gone, or not ours to inspect
            if used < size:
                break
            size *= 2
        else:
            continue
        for offset in range(0, used - _DARWIN_PROC_FD_INFO_SIZE + 1, _DARWIN_PROC_FD_INFO_SIZE):
            fd = struct.unpack_from("<i", listing.raw, offset)[0]
            record = ctypes.create_string_buffer(_DARWIN_FD_RECORD_SIZE)
            if lib.proc_pidfdinfo(pid, fd, _DARWIN_PIDFDVNODEPATHINFO, record,
                                  _DARWIN_FD_RECORD_SIZE) <= 0:
                continue
            raw = record.raw
            identity = (struct.unpack_from("<I", raw, _DARWIN_FD_DEV_OFFSET)[0],
                        struct.unpack_from("<Q", raw, _DARWIN_FD_INO_OFFSET)[0])
            target = raw[_DARWIN_FD_PATH_OFFSET:].split(b"\x00", 1)[0].decode("utf-8", "replace")
            yield pid, fd, target, identity


def _iter_darwin_sidecar_holders(db_path) -> list[tuple[int, str]]:
    """The macOS leg of :func:`iter_deleted_sqlite_sidecar_holders`: libproc enumeration matched
    against the watched sidecar paths, judged by identity.

    The watched side is resolved with ``os.path.realpath`` because libproc reports the kernel's
    path for the vnode, while ``os.path.abspath`` does not resolve symlinks -- a textual compare
    of the two silently misses every sidecar under a symlinked prefix (on macOS ``/var`` itself)."""
    base = os.path.realpath(os.path.abspath(os.fspath(db_path)))
    # APFS/HFS+ are case-insensitive by default and libproc reports the pathname as the opener
    # spelled it; ``os.path.normcase`` is the identity on darwin, so fold case here.
    watched = {path.casefold(): path for path in (base + "-wal", base + "-shm")}
    holders: list[tuple[int, str]] = []
    errors: list[BaseException] = []

    def _scan() -> None:
        try:
            for pid, _fd, target, identity in _iter_darwin_fd_targets():
                literal = watched.get(target.casefold())
                if literal is not None and _identity_is_truly_unlinked(identity, literal):
                    holders.append((pid, target))
        except BaseException as exc:
            errors.append(exc)

    # ponytail: abandoned daemon thread per timed-out scan; a kernel-blocked
    # proc_pidfdinfo cannot be interrupted, so expiry leaks one thread that
    # dies with the process. Fail open: partial/empty holders, never a refusal.
    worker = threading.Thread(target=_scan, daemon=True)
    worker.start()
    worker.join(_DARWIN_FD_SCAN_TIMEOUT_SECONDS)
    if worker.is_alive():
        logger.warning(
            "deleted-WAL holder scan timed out after %.1fs for %s; continuing fail-open",
            _DARWIN_FD_SCAN_TIMEOUT_SECONDS,
            db_path,
        )
        return []
    if errors:
        raise errors[0]
    return holders


def iter_deleted_sqlite_sidecar_holders(db_path) -> list[tuple[int, str]]:
    """Return processes holding an unlinked ``state.db-wal`` / ``-shm`` sidecar for *db_path*.

    Linux enumerates ``/proc/<pid>/fd`` (using the `` (deleted)`` suffix as a cheap pre-filter);
    macOS enumerates descriptors through libproc, because a retired generation there keeps its
    last pathname and no suffix marks it.  Either way the verdict is the same identity comparison:
    the fd must name a watched sidecar path while its ``(st_dev, st_ino)`` no longer matches what
    that path holds.  Windows returns ``[]`` -- it cannot unlink a held sidecar, so no retired
    generation can exist; any other platform returns ``[]`` as before.

    Includes this process: on the open/write refuse path the in-process writer holding the orphan
    inode must not mint a replacement WAL (``_foreign_state_db_holders`` skips this PID)."""
    if sys.platform == "win32":
        return []
    holders: list[tuple[int, str]] = []
    try:
        if sys.platform == "darwin":
            holders = _iter_darwin_sidecar_holders(db_path)
        elif sys.platform.startswith("linux"):
            watched = _watched_sqlite_sidecar_paths(db_path)
            for pid, target, fd_path in _iter_proc_fd_targets():
                canonical = canonical_sqlite_path(target)
                if (" (deleted)" in target and canonical in watched
                        and _fd_is_truly_unlinked(fd_path, watched[canonical])):
                    holders.append((pid, target))
    except Exception as exc:
        logger.debug("deleted-WAL holder scan failed for %s: %s", db_path, exc)
    return holders


def refuse_deleted_wal_generation(db_path, *, message: str) -> None:
    """Raise if any process holds a deleted WAL/SHM generation for *db_path*; called
    *before* ``sqlite3.connect`` so a second opener cannot mint a replacement WAL inode."""
    if not iter_deleted_sqlite_sidecar_holders(db_path):
        return
    logger.error(message)
    raise DeletedWalGenerationError(message)


class RetiredGenerationCaptureError(RuntimeError):
    """The retired WAL generation could not be captured durably; nothing was mutated."""


def _connect_tracked_db(path, tracking_path=None, **kwargs):
    """``sqlite3.connect`` that registers the open fd so byte-level probes of a live file are
    refused (an ``open()``/``close()`` would cancel every POSIX lock, even a running VACUUM's
    EXCLUSIVE).  The ONLY tolerated fallback is the helper being absent (scaffold/embed installs
    without hermes_cli); a real connection failure must propagate — a silent untracked retry
    would disable the guard for that connection."""
    try:
        from hermes_db.infra.sqlite.safe_read import connect_tracked
    except ImportError:
        logger.debug('hermes_db.infra.sqlite.safe_read unavailable; opening %s untracked (byte-probe guard inactive in this install)', path)
        return sqlite3.connect(str(path), **kwargs)
    # Open through THIS module's sqlite3.connect so tests patching hermes_state.sqlite3.connect keep control.
    return connect_tracked(path, tracking_path=tracking_path, connect_fn=sqlite3.connect, **kwargs)


def _preopen_header(path: Path, probe_bytes: int, force: bool) -> Optional[bytes]:
    """First ``probe_bytes`` of *path* read WITHOUT opening a SQLite connection, or None when the probe
    must not run: special files (a FIFO would block), unreadable paths, or — unless ``force`` — a path
    this process already has a connection to (``close()`` cancels every POSIX lock, even a running
    VACUUM's EXCLUSIVE; see #97568).  ``force=True`` only for offline files (quarantined copies, snapshots)."""
    try:
        if not path.is_file():
            return None
        path.stat()
        from hermes_db.infra.sqlite.safe_read import has_live_connection, read_header_bytes_preopen
        if not force and has_live_connection(path):
            return None
        return read_header_bytes_preopen(path, length=max(16, probe_bytes), force=force)
    except Exception:
        return None


def path_is_under(path: Path, root: Path) -> bool:
    """True when *path* is *root* or a file inside it (normcase, resolved)."""
    try:
        path_key = os.path.normcase(str(path.resolve()))
        root_key = os.path.normcase(str(root.resolve()))
    except OSError:
        path_key = os.path.normcase(str(path))
        root_key = os.path.normcase(str(root))
    return path_key == root_key or path_key.startswith(root_key + os.sep)


def header_probes_under(root: Path) -> dict[str, tuple[int, int, int]]:
    """Snapshot of the cached probes at or under *root*: key -> (fd, dev, ino)."""
    with _HEADER_PROBE_LOCK:
        entries = dict(_HEADER_PROBE_FDS)
    return {key: entry for key, entry in entries.items() if path_is_under(Path(key), root)}


def inodes_with_other_descriptors(identities: set[tuple[int, int]]) -> Optional[set[tuple[int, int]]]:
    """Which of *identities* (``(st_dev, st_ino)``) have a non-probe descriptor open in this
    process; None when the fd table is unreadable (callers then close nothing). Probes are left
    out: they hold no locks, so two spellings of one path must not pin each other. The probe lock
    is taken only to copy the probe fds, never across the scan, and never unbounded: callers run
    this while ``offline_file_access`` holds ``_live_lock``, and a writer holding the probe lock in
    ``_pread_db_range`` may be waiting on ``_live_lock`` behind a collection that finalizes an
    unclosed ``SessionDB``. On timeout this returns None, so the caller closes nothing."""
    if not _HEADER_PROBE_LOCK.acquire(timeout=_HEADER_PROBE_LOCK_TIMEOUT):
        logger.debug(
            "header-probe scan skipped: probe lock busy for %.2fs, closing nothing",
            _HEADER_PROBE_LOCK_TIMEOUT)
        return None
    try:
        probe_fds = {entry[0] for entry in _HEADER_PROBE_FDS.values()}
        probe_fds.update(_RETIRED_HEADER_PROBE_FDS)  # retired probes hold no locks either
    finally:
        _HEADER_PROBE_LOCK.release()
    descriptors = own_descriptors()
    if descriptors is None:
        return None
    return {ident for fd, ident in descriptors if fd not in probe_fds and ident in identities}


def close_header_probe_if_unchanged(key: str, expected: tuple[int, int, int]) -> bool:
    """False, and the fd stays, when the entry changed since the caller checked it, or when the
    probe lock cannot be taken within ``_HEADER_PROBE_LOCK_TIMEOUT`` seconds.

    This runs while ``offline_file_access`` holds ``_live_lock``; waiting unbounded for the probe
    lock here can deadlock against a collection that finalizes an unclosed ``SessionDB`` inside
    ``_pread_db_range`` (probe lock held, finalizer needs ``_live_lock``). On timeout the entry is
    left alone and the sweep simply keeps the probe for another round."""
    if not _HEADER_PROBE_LOCK.acquire(timeout=_HEADER_PROBE_LOCK_TIMEOUT):
        logger.debug(
            "header probe of %s kept: probe lock busy for %.2fs, the next sweep retries",
            key, _HEADER_PROBE_LOCK_TIMEOUT)
        return False
    try:
        if _HEADER_PROBE_FDS.get(key) != expected:
            return False
        del _HEADER_PROBE_FDS[key]
        with contextlib.suppress(OSError):
            os.close(expected[0])
    finally:
        _HEADER_PROBE_LOCK.release()
    return True
