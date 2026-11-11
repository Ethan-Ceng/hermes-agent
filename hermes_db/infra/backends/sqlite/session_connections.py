from __future__ import annotations

"""Read-connection budgeting for SQLiteConnections's WAL read path: per-file and
process-wide permit ceilings plus a descriptor-headroom gate, so N handles on
one state.db cannot walk the process into EMFILE. Idle pooled connections keep
their permit and are reclaimable across peers on the same path."""

import errno
import logging
import os
import threading
import time
import weakref
from pathlib import Path
from typing import Iterator, Optional


# caplog tests pin the "hermes_state" logger name.
logger = logging.getLogger("hermes_state")

# Ceiling on read-only connections ALIVE at once against one database FILE (idle
# pooled + checked out, over every SQLiteConnections on that file). One constant for both
# the pool maxsize and the permit count: a LifoQueue only caps how many are
# *returned*, and EMFILE is a peak-instant condition, so a connection holds a
# permit for its whole lifetime; once permits are gone reads degrade to the
# locked writer connection — slower, but not a wedge the supervisor can't see.
# Transient SQLITE_IOERR retry budget for READ-ONLY opens (#100436). A WAL database being actively written
# (checkpoint, WAL reset/truncate, frame flush) can surface "disk I/O error" to a concurrent ``mode=ro``
# reader in a millisecond-wide transition window: the read-only connection cannot perform the WAL recovery a
# read through a stale or mid-update -shm file needs, because recovery requires writing the -shm index,
# which mode=ro refuses. The window closes on its own (the writer finishes the transition), so a bounded
# number of short retries makes the open succeed instead of 500-ing the whole /api/sessions poll (or any
# other read-only opener). Deliberately NOT attempted on writable opens: a writer owns the transition, so an
# IOERR there means a real storage/fd problem.
_READ_POOL_MAX = 8

# Ceiling ALIVE in this PROCESS across every state.db (a multiplexed gateway
# opens one per profile); three profiles' worth, then readers degrade likewise.
# _READ_POOL_MAX bounds one file. A multiplexed gateway serves N profiles from one process and each profile
# has its OWN state.db, so a per-file ceiling still lets the descriptor cost grow with the profile count —
# the same shape as the per-instance bug, one level out (#98573). Past it, readers on the (N+1)th file
# degrade to their writer connection instead of opening descriptors, which is the same trade _READ_POOL_MAX
# makes and for the same reason: a slow read path is recoverable, a process-wide EMFILE is not.
_READ_POOL_PROCESS_MAX = 24

# Warn past this many SQLiteConnections handles on one file in one process (diagnostic:
# writer connections cannot be rationed the way read connections can).
_HANDLES_PER_PATH_WARN = 4

# Descriptors kept in reserve for everything that is NOT this module (httpx
# sockets, terminal pipes, log files): the EMFILE SQLite pushes over surfaces elsewhere.
# The ceilings above bound Hermes's SQLite descriptors, which is only ever part of the fd table. The #98573
# report is exactly that case: ~20 state.db descriptors were not the whole 256, they were the share that
# pushed httpx and terminal pipes over, and the EMFILE surfaced in tools/terminal_tool.py rather than here.
# So the read pool also yields when the PROCESS is close to its limit, whatever is consuming it.
_FD_HEADROOM_RESERVE = 64

# The fd count is a directory listing; cache it briefly so a read burst isn't a
# syscall per query (staleness lets through at most the ceiling's worth of opens).
_FD_USAGE_CACHE_SECONDS = 0.25

_process_read_permits = threading.BoundedSemaphore(_READ_POOL_PROCESS_MAX)

# Read opens refused for low descriptor headroom — the only visible signal the
# guard fires. Guarded by _read_budgets_lock.
_read_open_denied_fd_headroom = 0

_fd_usage_lock = threading.Lock()
_fd_usage_cache: tuple[float, Optional[int]] = (0.0, None)


def _proc_fd_targets(pid: int) -> Iterator[tuple[str, str]]:
    """Yield ``(readlink target, fd path)`` for every entry in /proc/<pid>/fd (unreadable
    links skipped). Raises OSError when the fd directory itself cannot be listed."""
    fd_dir = f"/proc/{pid}/fd"
    for fd in os.listdir(fd_dir):
        fd_path = f"{fd_dir}/{fd}"
        try:
            yield os.readlink(fd_path), fd_path
        except OSError:
            continue


def _open_fd_count() -> Optional[int]:
    """Open descriptors in THIS process; None when unmeasurable (Windows: no fd
    dir, correctly inert); -1 when the probe itself hit EMFILE/ENFILE (no headroom)."""
    for fd_dir in ("/proc/self/fd", "/dev/fd"):
        try:
            return len(os.listdir(fd_dir))
        except OSError as exc:
            if exc.errno in (errno.EMFILE, errno.ENFILE):
                return -1
    return None


def _fd_soft_limit() -> Optional[int]:
    """The process's soft RLIMIT_NOFILE, or None when there is no usable one."""
    try:
        import resource
    except ImportError:
        return None
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (AttributeError, OSError, ValueError):
        return None
    if soft in (resource.RLIM_INFINITY, -1):
        return None
    return int(soft)


def _fd_headroom_ok() -> bool:
    """Can the process spare a descriptor for a new read connection? Fails OPEN
    when unmeasurable (refusing every read would be a self-inflicted convoy);
    fails CLOSED only on evidence (measured shortfall or a starved probe)."""
    soft = _fd_soft_limit()
    if soft is None:
        return True
    global _fd_usage_cache
    now = time.monotonic()
    with _fd_usage_lock:
        stamp, cached = _fd_usage_cache
        fresh = cached is not None and (now - stamp) < _FD_USAGE_CACHE_SECONDS
    if not fresh:
        cached = _open_fd_count()
        with _fd_usage_lock:
            _fd_usage_cache = (now, cached)
    if cached is None:
        return True
    return cached >= 0 and (soft - cached) > _FD_HEADROOM_RESERVE


def _reclaim_idle_read_conn_anywhere() -> bool:
    """Close one idle read connection on ANY path: the process ceiling is shared
    across files, so a quiet profile must not hold descriptors a busy one needs."""
    with _read_budgets_lock:
        budgets = list(_read_budgets.values())
    return any(budget.reclaim_idle() for budget in budgets)


class _PathReadBudget:
    """Read-connection permits for ONE database file, shared process-wide
    (per-instance semaphores let N SQLiteConnectionss peak at N x (1 + MAX)). An idle
    pooled connection keeps its permit, so a permit miss first reclaims an IDLE
    connection from a peer on the same path.

    ``_READ_POOL_MAX`` used to be enforced by a ``BoundedSemaphore`` owned by each SQLiteConnections, which bounded
    the wrong noun: the descriptors are spent on a *file*, so N SQLiteConnections objects on one state.db each got
    their own allowance and peak scaled as ``N x (1 + _READ_POOL_MAX)``. A long-lived gateway holds at least
    two (``SessionStore`` and ``GatewayRunner`` open independent handles per profile path) and the count
    grows with the profile count, which is how a healthy process walked into EMFILE — #98573.
    """

    def __init__(self) -> None:
        self.permits = threading.BoundedSemaphore(_READ_POOL_MAX)
        self._lock = threading.Lock()
        # Weak: a SQLiteConnections dropped without close() must not pin peers' budget.
        self._members: weakref.WeakSet[SQLiteConnections] = weakref.WeakSet()
        self._duplicate_handles_warned = False

    def register(self, db: SQLiteConnections) -> None:
        with self._lock:
            self._members.add(db)
            # Only writable handles carry the cost the warning names (writer connection, write
            # lock, close-time checkpoint). Read-only attaches (dashboard routers, status/lookup
            # one-shots) open per request by design and must not trip it.
            handles = sum(
                1 for member in self._members
                if not member.read_only and member._conn is not None
            )
            warn = (handles > _HANDLES_PER_PATH_WARN and not self._duplicate_handles_warned)
            if warn:
                self._duplicate_handles_warned = True
                # Same population as `handles`: the read-only attaches the count skips
                # must not reappear in the list, or the list no longer explains the number.
                creation_sites = ", ".join(sorted(
                    member._creation_site for member in self._members if not member.read_only
                ))
        if warn:
            # Writer connections cannot be capped; the only bound is not opening
            # redundant handles, so make the duplicate visible before it's an incident.
            logger.warning(
                # The only real bound on writers is not opening redundant handles in the first place (which
                # is what GatewayRunner borrowing SessionStore's handle does, #98573), so the next duplicate
                # should be visible before it becomes an incident rather than inferred from an lsof after
                # one.
                "%d live SessionDB handles on %s in this process; each holds "
                "its own writer connection (read connections are capped at %d "
                "for the file). A long-lived process should share one handle per path. "
                "Created at: %s",
                handles, db.db_path, _READ_POOL_MAX, creation_sites,
            )

    def unregister(self, db: SQLiteConnections) -> None:
        """Remove a closed writer from duplicate-handle diagnostics immediately."""
        with self._lock:
            self._members.discard(db)

    def acquire(self, requester: SQLiteConnections) -> bool:
        """Take a permit for a new read connection, or refuse (caller degrades to the
        locked writer connection). Gates, broadest first: fd headroom, process
        ceiling, this file's ceiling."""
        if not _fd_headroom_ok():
            global _read_open_denied_fd_headroom
            with _read_budgets_lock:
                _read_open_denied_fd_headroom += 1
            return False
        if not self._acquire_process_permit():
            return False
        if self._acquire_path_permit(requester):
            return True
        _process_read_permits.release()
        return False

    def release(self) -> None:
        """Return one connection's permits. Pairs with a successful acquire()."""
        self.permits.release()
        _process_read_permits.release()

    def _acquire_process_permit(self) -> bool:
        # Another thread may take a freed permit first: legitimate loss, no looping.
        return _process_read_permits.acquire(blocking=False) or (
            _reclaim_idle_read_conn_anywhere() and _process_read_permits.acquire(blocking=False)
        )

    def _acquire_path_permit(self, requester: SQLiteConnections) -> bool:
        return self.permits.acquire(blocking=False) or (
            self.reclaim_idle(exclude=requester) and self.permits.acquire(blocking=False)
        )

    def reclaim_idle(self, exclude: Optional[SQLiteConnections] = None) -> bool:
        """Close one idle pooled connection held by a member; True if one went.
        Its release() returns both permits, so both ceilings reclaim through here."""
        with self._lock:
            members = [db for db in self._members if db is not exclude]
        return any(member._evict_one_idle_read_conn() for member in members)


# canonical db path -> permits for that file. Weak values: the budget lives only
# while some SQLiteConnections on the path holds it, so tmp_path churn can't grow this.
_read_budgets: weakref.WeakValueDictionary[str, _PathReadBudget] = (weakref.WeakValueDictionary())
_read_budgets_lock = threading.Lock()


def _read_budget_key(db_path) -> str:
    """Canonicalise a db path so two spellings share one budget."""
    try:
        return str(Path(db_path).resolve())
    except OSError:
        return str(db_path)


def _read_budget_for(db_path) -> _PathReadBudget:
    key = _read_budget_key(db_path)
    with _read_budgets_lock:
        budget = _read_budgets.get(key)
        if budget is None:
            budget = _PathReadBudget()
            _read_budgets[key] = budget
        return budget

import queue
import sqlite3
from contextlib import contextmanager, suppress

from hermes_db.infra.backends.sqlite import wal
from hermes_db.infra.backends.sqlite import lockguard as _lockguard
from hermes_db.infra.backends.sqlite import generation
from hermes_db.infra.backends.sqlite.generation import (StateDbReplacedError, DeletedWalGenerationError, RetiredGenerationCaptureError, stat_db_file_identity as _stat_db_file_identity, canonical_sqlite_path)
import sys

_READ_OPEN_RETRY_SECONDS = 60.0
_READ_BUSY_TIMEOUT_S = 5.0


def _close_time_checkpoint_configurable():
    return (getattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None) is not None
            and hasattr(sqlite3.Connection, "setconfig"))


class SQLiteConnections:
    """Concrete native connection state; applications supply a resolved path, URI and PRAGMAs."""

    def __init__(self, db_path, *, read_only, read_uri, pragmas, creation_site,
                 capture_retired, replaced_message, deleted_message):
        self.db_path = Path(db_path)
        self.read_only = read_only
        self.read_uri = read_uri
        self.pragmas = dict(pragmas)
        self._creation_site = creation_site
        self._lock = threading.Lock()
        self._conn = None
        self._wal_active = False
        self.capture_retired = capture_retired
        self.replaced_message, self.deleted_message = replaced_message, deleted_message
        self._db_corrupt, self._db_corrupt_reason = False, ""
        self._db_file_identity = None
        self._db_file_application_id = 0
        self._db_sidecar_identity = {}
        self._db_replaced = self._db_wal_generation_lost = False
        self._retired_generation_capture = None
        self._retired_capture_lock = threading.Lock()
        self._retire_connection = None
        self._connection_pinned = False
        self._wal_lock_guard = {}
        self._read_pool = queue.LifoQueue(maxsize=_READ_POOL_MAX)
        self._read_budget = _read_budget_for(self.db_path)
        self._read_permits = self._read_budget.permits
        self._read_conns_lock = threading.Lock()
        self._read_conns_closed = False
        self._read_open_failed_at = 0.0

    def attach_writer(self, conn, *, wal_active):
        """Take ownership after an application's explicit Schema lifecycle has succeeded."""
        self._conn = conn
        self._wal_active = wal_active
        self._read_budget.register(self)

    def _connect_read_only(self, timeout):
        conn = generation._connect_tracked_db(self.read_uri, tracking_path=self.db_path,
                                        uri=True, check_same_thread=False, timeout=timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _close_connection_quietly(conn: Optional[sqlite3.Connection]) -> None:
        """Close a partially initialized connection without masking its error."""
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            logger.debug("Could not close a SessionDB connection", exc_info=True)


    def _close_conn_logged(self, conn, label: str) -> None:
        """Close *conn*; a failing close leaks a tracked fd: logged at WARNING, never swallowed."""
        try:
            conn.close()
        except Exception as exc:
            logger.warning("%s close failed for %s: %s", label, self.db_path, exc)


    def _get_read_conn(self) -> Optional[sqlite3.Connection]:
        """Open a fresh read-only connection, or None when unavailable (callers
        return it to self._read_pool). WAL only: WAL readers never block on the
        writer, so reads skip self._lock; under DELETE journal mode (NFS fallback)
        readers hit SQLITE_BUSY storms, so the legacy locked path stays. Autocommit
        reads see everything committed so far (read-your-writes for flush-then-search)."""
        if not self._wal_active or self.read_only:
            return None
        with self._read_conns_lock:
            failed_at = self._read_open_failed_at
            backing_off = failed_at and time.monotonic() - failed_at < _READ_OPEN_RETRY_SECONDS
            if self._read_conns_closed or backing_off:
                return None
        # Permit BEFORE the open: openers race for permits, not descriptors.
        if not self._read_budget.acquire(self):
            logger.debug(
                "read pool at capacity (%d) for %s; serving this read from the "
                "locked writer connection", _READ_POOL_MAX, self.db_path,
            )
            return None
        conn = None  # bound before the try so the handlers can close a half-open one
        try:
            conn = self._connect_read_only(timeout=_READ_BUSY_TIMEOUT_S)
            wal.apply_database_pragmas(conn, pragmas=self.pragmas, db_label="state.db")
        except BaseException as exc:
            # A half-open connection (open ok, pragmas failed) is a live tracked descriptor,
            # the leak shape this pool exists to fix; a stranded permit would shrink the read
            # path by one slot forever. (Not _close_read_conn: callers release their own permit.)
            if conn is not None:
                self._close_conn_logged(conn, "partially-opened read conn")
            self._read_budget.release()
            if not isinstance(exc, sqlite3.Error):
                raise
            with self._read_conns_lock:
                self._read_open_failed_at = time.monotonic()
            logger.debug("read-only connection open failed for %s", self.db_path, exc_info=True)
            return None
        return conn


    def _evict_one_idle_read_conn(self) -> bool:
        """Close one idle pooled connection (a peer on the same file wants its permit); never a live one."""
        try:
            conn = self._read_pool.get_nowait()
        except queue.Empty:
            return False
        self._close_read_conn(conn)
        return True


    def _close_read_conn(self, conn) -> None:
        """Close a pooled read connection and release its permit even when the close fails (withholding
        it would narrow the read path forever). Over-releasing the BoundedSemaphore raises ValueError."""
        try:
            self._close_conn_logged(conn, "read-conn")
        finally:
            self._read_budget.release()


    def _checkout_read_conn(self) -> Optional[sqlite3.Connection]:
        """Borrow a read connection, opening on a miss; None when the read path is unavailable.
        A pool hit costs no permit (the connection already holds one)."""
        if not self._wal_active or self.read_only:
            return None
        try:
            return self._read_pool.get_nowait()
        except queue.Empty:
            return self._get_read_conn()


    @contextmanager
    def pooled_read(self):
        """Borrow only a pooled reader; None tells the business owner to use its writer fallback."""
        conn = self._checkout_read_conn()
        if conn is None:
            yield None
            return
        try:
            yield conn
        finally:
            returned = False
            with self._read_conns_lock:
                if not self._read_conns_closed:
                    try:
                        self._read_pool.put_nowait(conn)
                        returned = True
                    except queue.Full:
                        pass
            if not returned:
                self._close_read_conn(conn)

    def close_readers(self):
        """Close idle readers now; in-flight borrowers close on return and release their permits."""
        with self._read_conns_lock:
            self._read_conns_closed = True
        while self._evict_one_idle_read_conn():
            pass


    def _record_db_file_identity(self, *, read_attempts=3, read_backoff=0.05):
        """Snapshot inode plus the on-disk generation header when present."""
        self._db_file_identity = _stat_db_file_identity(self.db_path)
        self._db_sidecar_identity = generation._stat_sqlite_sidecar_identity(self.db_path)
        disk_id = generation._read_sqlite_application_id(self.db_path)
        if disk_id:
            self._db_file_application_id = disk_id
        elif self._conn is not None and not self._db_file_application_id:
            try:
                pragma_row = self._read_application_id(read_attempts, read_backoff)
            except sqlite3.DatabaseError as exc:
                return exc
            except sqlite3.Error:
                return None
            if pragma_row and pragma_row[0]:
                self._db_file_application_id = int(pragma_row[0])

    def _db_file_was_replaced(self) -> bool:
        """True when the path no longer names the file this instance opened."""
        recorded = self._db_file_identity
        if recorded is not None and _stat_db_file_identity(self.db_path) != recorded:
            return True
        recorded_app = int(self._db_file_application_id or 0)
        if not recorded_app:
            return False
        # Header 0 = WAL not yet checkpointed, not a replace; a real replacement is nonzero.
        disk_app = generation._read_sqlite_application_id(self.db_path)
        return bool(disk_app and disk_app != recorded_app)

    def _wal_generation_was_lost(self) -> bool:
        """True when the WAL/SHM generation this handle opened is gone. Recorded
        generation: pure stat (no /proc walk on healthy writes). Empty identity
        (WAL appeared after open, or cleared by a clean close()): probe
        /proc/self/fd for deleted sidecars and adopt the current ones once clean."""
        recorded = self._db_sidecar_identity or {}
        base = os.fspath(self.db_path)
        if recorded:
            return any(
                _stat_db_file_identity(Path(base + suffix)) != ident for suffix, ident in recorded.items()
            )
        if not self._wal_active:  # no sidecar generation to lose; keep /proc off the hot path
            return False
        if sys.platform.startswith("linux"):
            watched = generation._watched_sqlite_sidecar_paths(self.db_path)
            try:
                for target, fd_path in _proc_fd_targets(os.getpid()):
                    canonical = canonical_sqlite_path(target)
                    if (" (deleted)" in target and canonical in watched
                            and generation._fd_is_truly_unlinked(fd_path, watched[canonical])):
                        return True
            except OSError:
                return False
        # Probe clean (or unavailable): adopt the current sidecar generation.
        current_identity = generation._stat_sqlite_sidecar_identity(self.db_path)
        if current_identity:
            self._db_sidecar_identity = current_identity
        return False

    def _halt_if_db_generation_changed(self) -> None:
        """Stop writes (logging once) when the file was replaced or its WAL/SHM generation
        is gone: never run in-file repair on a new generation, never keep committing on a
        split WAL. Both flags are sticky."""
        # A reopen resolves the PATH again — if the file at that path is no longer the one this instance
        # originally opened (out-of-band restore/cp/mv), reconnecting would write into the new generation
        # through stale WAL/shm assumptions (#89332). Refuse instead.
        if self._db_replaced or self._db_file_was_replaced():
            self._db_replaced = True
            self._disable_close_time_checkpoint()
            logger.error(self.replaced_message)
            raise StateDbReplacedError(self.replaced_message)
        if self._db_wal_generation_lost or self._wal_generation_was_lost():
            self._db_wal_generation_lost = True
            self._disable_close_time_checkpoint()
            try:
                self._capture_retired_generation("halt")
            except RetiredGenerationCaptureError as exc:
                logger.error(
                    "Could not capture the retired WAL generation of %s at halt: %s. close() retries "
                    "the capture and refuses to settle without it.", self.db_path, exc,
                )
            logger.error(self.deleted_message)
            raise DeletedWalGenerationError(self.deleted_message)

    def _capture_retired_generation(self, trigger: str) -> Path:
        """Durably capture the lost WAL generation this handle still holds open, once per handle.

        The quarantine keeps the retired frames from being checkpointed under wrong page numbers,
        but they live only in an unlinked inode that dies with this process's last descriptor, and
        the canonical DeletedWalGenerationError remediation is to stop the writers. Capturing at the
        first halt (or at close(), whichever sees the loss first) makes "preserve" outlive the
        process. Raises RetiredGenerationCaptureError; nothing is mutated on failure."""
        with self._retired_capture_lock:
            if self._retired_generation_capture is not None:
                return self._retired_generation_capture
            artifact = self.capture_retired(
                self.db_path, sidecar_identity=dict(self._db_sidecar_identity or {}), trigger=trigger,
            )
            self._retired_generation_capture = artifact
        logger.warning(
            "Captured the retired WAL generation of %s at %s to %s; read its manifest.json before deciding "
            "whether those frames belong on top of the file now at the path.", self.db_path, trigger, artifact,
        )
        return artifact

    def _raise_if_db_replaced(self) -> None:
        """Sticky-flag fast path (no log spam on every write), then the live probe."""
        if self._db_replaced:
            raise StateDbReplacedError(self.replaced_message)
        if self._db_wal_generation_lost:
            raise DeletedWalGenerationError(self.deleted_message)
        self._halt_if_db_generation_changed()

    def _disable_close_time_checkpoint(self) -> bool:
        """Best-effort SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE (Python 3.12+): sqlite3's
        close() otherwise runs the internal last-connection checkpoint that wrote
        the incident's pages under wrong page numbers (see StateDbCorruptError and
        the generation-loss halts).
        <3.12 has no setconfig, so a lost-generation handle is retired unclosed
        instead (see close()): closing its last descriptor could both run that
        checkpoint and discard committed data present only in an unlinked WAL."""
        flag = getattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None)
        conn = self._conn
        setconfig = getattr(conn, "setconfig", None)
        if flag is None or setconfig is None:
            # Same predicate as _close_time_checkpoint_configurable() plus the per-instance
            # getattr: __init__ binds no retirement capability when either half is missing,
            # and close() must agree with that decision or the lost handle would neither
            # setconfig nor pin.
            return False
        try:
            setconfig(flag, True)
        except Exception:
            # No retention capability is bound on this runtime, so close() will let SQLite run the
            # checkpoint over the newer generation: say so where an operator can see it.
            logger.error(
                "Could not disable SQLite's close-time checkpoint on the quarantined handle for %s; "
                "closing it may checkpoint retired frames over the newer generation.",
                self.db_path, exc_info=True,
            )
            return False
        return True

    def _pin_connection(self, conn) -> None:
        """Retain the exact quarantined connection past GC and interpreter teardown (once per handle).

        Takes the connection as a parameter: callers are lock-held close paths, and the
        writer-conn thread-safety audit flags self._conn in functions outside `with self._lock`."""
        if not self._connection_pinned:
            self._retire_connection(conn)
            self._connection_pinned = True

    def _settle_lost_generation_locked(self) -> bool:
        """Capture the retired generation; return whether the handle must be retired unclosed.

        Where SQLite's close-time checkpoint cannot be switched off (no setconfig, Python < 3.12),
        sqlite3_close would write the retired frames over the newer generation, so the exact
        connection is retired unclosed instead. A failed capture leaves the handle open for a retry
        -- but the pin is taken FIRST on such a runtime: every production caller reaches close()
        through hermes_state_registry.release_or_close, which swallows the error, so an interpreter
        exit before the retry must not be able to checkpoint the stale frames either."""
        self._db_wal_generation_lost = True
        retire_without_close = not self._disable_close_time_checkpoint() and self._retire_connection is not None
        try:
            artifact = self._capture_retired_generation("close")
        except RetiredGenerationCaptureError as exc:
            if retire_without_close:
                self._pin_connection(self._conn)
            logger.error(
                "Could not capture the retired WAL generation of %s at close: %s. The handle stays open "
                "and close() retries the capture; those frames are NOT yet preserved.", self.db_path, exc,
            )
            raise
        logger.warning(
            "Skipping the close-time WAL checkpoint for %s: this handle's WAL/SHM generation "
            "was deleted or replaced; the retired generation is captured at %s. Stop the other "
            "writers before reopening and inspect the capture before deciding its disposition.",
            self.db_path, artifact,
        )
        if retire_without_close:
            logger.warning(
                "Retaining the quarantined connection for %s unclosed: this runtime cannot "
                "switch off SQLite's close-time checkpoint.", self.db_path,
            )
        return retire_without_close

    def _try_wal_checkpoint(self) -> None:
        """Best-effort PASSIVE WAL checkpoint; never raises. PASSIVE never blocks writers;
        TRUNCATE corrupted B-trees on 65K+ page databases under exclusive-lock I/O pressure.

        Previous TRUNCATE strategy caused B-tree corruption on large databases (65K+ pages) due to the
        exclusive-lock I/O pressure from checkpointing thousands of frames at once (issue #45383).
        """
        if self._quarantine_reason() is not None:
            return
        try:
            with self._lock:
                if self._conn is None:
                    return  # closed underneath the timer: nothing to checkpoint, nothing to re-guard
                if self._wal_lock_guard:
                    _lockguard.hold(self.db_path, self._wal_lock_guard)  # a -shm minted after open
                result = self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                if result and result[1] > 0:
                    logger.debug("WAL checkpoint: %d/%d pages checkpointed", result[2], result[1])
        except Exception as exc:
            logger.warning("WAL checkpoint (PASSIVE) failed: %s", exc)

    def _quarantine_reason(self):
        if self._db_corrupt:
            return f"structural corruption ({self._db_corrupt_reason})"
        if self._db_replaced:
            return "a replaced state.db file"
        if self._db_wal_generation_lost:
            return "a deleted WAL generation (split-brain)"
        return None

    def connect_writer(self):
        self.prepare_writer()
        return generation._connect_tracked_db(str(self.db_path), check_same_thread=False,
                                   timeout=1.0, isolation_level=None)

    def connect_existing_writer(self):
        self.prepare_writer()
        uri = self.db_path.resolve().as_uri() + "?mode=rw"
        return generation._connect_tracked_db(
            uri, tracking_path=self.db_path, uri=True, check_same_thread=False,
            timeout=1.0, isolation_level=None,
        )

    @contextmanager
    def write_transaction(self):
        """Caller holds the resource lock and has checked business/generation guards."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            try:
                self._conn.rollback()
            except Exception:
                logger.debug("Rollback failed after transaction error", exc_info=True)
            raise

    def close(self):
        # Closed flag first: an in-flight reader then closes its own connection.
        with self._read_conns_lock:
            self._read_conns_closed = True
        while self._evict_one_idle_read_conn():
            pass
        with self._lock:
            if self._conn:
                generation_lost = not self.read_only and (
                    self._db_wal_generation_lost
                    or (bool(self._db_sidecar_identity) and self._wal_generation_was_lost())
                )
                # Loss is settled here, not at exit: the unlinked WAL inode dies with this process's
                # last descriptor (the capture raises and the handle stays open when it fails).
                retire_without_close = generation_lost and self._settle_lost_generation_locked()
                quarantine_reason = None if generation_lost else self._quarantine_reason()
                if quarantine_reason is not None:
                    logger.warning(
                        "Skipping the close-time WAL checkpoint for %s: this "
                        "handle observed %s. Take a snapshot of state.db, -wal and -shm "
                        "before restarting, then run `hermes sessions recover --source %s --inspect-only`.",
                        self.db_path, quarantine_reason, self.db_path,
                    )
                elif not self.read_only and not generation_lost:  # PASSIVE, not TRUNCATE (see docstring)
                    try:
                        # Every cron run_agent opens+closes a transient SessionDB, so a TRUNCATE here fires
                        # a full WAL reset many times/hour, racing the gateway's long-lived writer on large
                        # WAL databases and tearing hot B-tree pages -- the #45383 corruption this class's
                        # own periodic checkpoint was already made PASSIVE to avoid. TRUNCATE belongs only
                        # on a sole-opener/quiescent connection.
                        self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    except Exception as exc:
                        logger.debug("WAL checkpoint (PASSIVE) at close failed: %s", exc, exc_info=True)
                _lockguard.release(self._wal_lock_guard)  # before the close: see release()
                if retire_without_close:
                    self._pin_connection(self._conn)
                    self._conn = None
                else:
                    conn, self._conn = self._conn, None
                    self._close_connection_quietly(conn)
                    # Only a clean close ends the generation; retain the recorded
                    # identity when retiring an unsafe handle.
                    self._db_sidecar_identity = {}
        self._read_budget.unregister(self)  # idempotent: a never-registered (failed-init) handle is a no-op

    @contextmanager
    def read_locked_writer(self):
        """Read on the writer while the caller holds this resource's lock."""
        conn = self._conn
        if self._wal_active or self.read_only:
            yield conn
            return
        previous_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.execute(f"PRAGMA busy_timeout={int(_READ_BUSY_TIMEOUT_S * 1000)}")
        try:
            yield conn
        finally:
            with suppress(sqlite3.Error):
                conn.execute(f"PRAGMA busy_timeout={int(previous_ms)}")

    def hold_wal_guard(self):
        if self._wal_active:
            self._wal_lock_guard = _lockguard.hold(self.db_path)

    def prepare_writer(self):
        """Bind unsafe-close retirement before opening or touching application files."""
        if (self._retire_connection is None and not self.read_only
                and not _close_time_checkpoint_configurable()):
            self._retire_connection = generation._prepare_connection_retirement()

    def _read_application_id(self, attempts, backoff):
        for attempt in range(attempts + 1):
            try:
                with self._lock:
                    return self._conn.execute("PRAGMA application_id").fetchone()
            except sqlite3.OperationalError as exc:
                if attempt >= attempts or "disk i/o error" not in str(exc).lower():
                    raise
                time.sleep(backoff)
