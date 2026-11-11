#!/usr/bin/env python3
"""SQLite state store for Hermes Agent: session metadata, message history, model
config, FTS5 search. WAL mode (concurrent readers + one writer); compression
splits sessions via parent_session_id chains; sessions are source-tagged
('cli', 'telegram', ...). Batch-runner / RL trajectories live elsewhere.
"""
from hermes_db.domains.sessions.rules import AUTO_PRUNE_STALE_OPEN_SOURCES

import asyncio
import atexit
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from hermes_dir_acl import make_user_dir

from hermes_constants import get_hermes_home, mkdir_under_hermes_home
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, TypeVar

from hermes_state_common import TITLE_SOURCE_DERIVED as _TITLE_SOURCE_DERIVED, TITLE_SOURCE_LLM as _TITLE_SOURCE_LLM, TITLE_SOURCE_USER as _TITLE_SOURCE_USER, escape_like as _escape_like, _placeholders
from hermes_state_holders import read_only_db_uri
from hermes_state_pidns import holder_pid_checkable
from hermes_state_health import (
    STORAGE_CORRUPT, mark_storage_corrupt, note_storage_error, storage_corrupt_reason, storage_state,
)
from hermes_state_errors import _DELETED_WAL_GENERATION_MSG, _DISK_IO_ERROR_MARKER, _STATE_DB_CORRUPT_MSG, _STATE_DB_GENERATION_KEY, _STATE_DB_REPLACED_MSG, SessionCompressionInProgressError, StateDbCorruptError, _is_no_more_rows, classify_persistence_error, is_malformed_db_error, is_malformed_schema_error
from hermes_db.infra.backends.sqlite.runtime import is_sqlite_lock_error
from hermes_db.infra.backends.sqlite.generation import DeletedWalGenerationError, StateDbReplacedError
from hermes_state_guard import (
    _STATE_DB_GUARD_BYPASS_ENV, _in_test_context, _is_production_state_db, _real_platform_state_root,
    _register_test_instance, _set_last_init_error, get_last_init_error,
)
from hermes_db.infra.backends.sqlite.session_connections import SQLiteConnections
from hermes_state_sessions import SessionSessionsMixin
from hermes_state_fts import SessionFtsSetupMixin
from hermes_state_portability import SessionPortabilityMixin
from hermes_state_telegram import SessionTelegramTopicsMixin
from hermes_state_schema import SessionSchemaMixin
import hermes_state_holders as _state_holders
from hermes_state_lockowners import log_write_lock_holders
from hermes_db.infra.backends.sqlite.generation import refuse_deleted_wal_generation
from hermes_cli import db_session_schema
from hermes_cli.db_session_schema import _secure_state_db_files
from hermes_state_messages import SessionMessagesMixin
from hermes_state_prune_rewrite import SessionPruneRewriteMixin
from hermes_state_api_content import SessionApiContentMixin
from hermes_state_coverage import SessionCoverageMixin
from hermes_state_rewind import SessionRewindMixin
from hermes_db.infra.backends.sqlite.wal import _WAL_INCOMPAT_MARKERS
from hermes_cli.db_sqlite_policy import apply_database_pragmas, capture_database_pragmas
from hermes_state_repair import _claim_repair_attempt, preflight_db_writability, repair_state_db_schema
from hermes_state_titles import SessionTitlesMixin
from hermes_state_prompt_refresh import SessionPromptRefreshMixin
from hermes_state_usage import SessionUsageMixin
from hermes_state_maintenance import SessionMaintenanceMixin
from hermes_state_gateway import SessionGatewayMixin
from hermes_state_compression import SessionCompressionMixin
from hermes_state_search import SessionSearchMixin

try:  # Hard dependency, but tolerate scaffold-phase imports before pip install.
    import psutil
except ImportError:  # pragma: no cover - stripped/scaffold installs only
    psutil = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_MAX_SAFE_MESSAGES = 20_000  # resume/export guard default


def _configured_transcript_limit(key: str, fallback: int = _MAX_SAFE_MESSAGES) -> int:
    """``sessions.<key>`` from config.yaml (lazy import: circular at load), else *fallback*; 0 disables."""
    try:
        from hermes_cli.config import load_config_readonly
        value = (load_config_readonly().get("sessions") or {}).get(key)
        if value is None:
            return fallback
        limit = int(value)
        return limit if limit >= 0 else fallback
    except Exception:
        return fallback


def resolved_max_resume_messages() -> int:
    return _configured_transcript_limit("max_resume_messages")


def resolved_max_export_messages() -> int:
    return _configured_transcript_limit("max_export_messages")


class SessionResumeTooLargeError(ValueError):
    def __init__(
        self, message_count: int, limit: int = _MAX_SAFE_MESSAGES, scope: str = "across its lineage",
    ):
        self.message_count, self.limit = message_count, limit
        self.scope = scope
        super().__init__(
            f"This session is too long to reload safely ({message_count} messages; limit {limit}). "
            "Start a fresh chat and keep a copy with the dashboard Sessions page's Export action or "
            "`hermes sessions export --format md --session-id <id>` (neither is capped), or raise the limit "
            "with `hermes config set sessions.max_resume_messages 0`."
        )


class SessionExportTooLargeError(ValueError):
    def __init__(self, session_id: str, message_count: int, limit: int = _MAX_SAFE_MESSAGES):
        self.session_id, self.message_count, self.limit = session_id, message_count, limit
        # User-facing refusal shared by every in-memory JSON/JSONL export (CLI and console).
        super().__init__(
            f"Session '{session_id}' has more than {limit:,} exportable messages; the JSON/JSONL "
            "backup is built in memory and capped per session. Use the dashboard Sessions page's streaming "
            "Export action, or set sessions.max_export_messages: 0 in config.yaml to disable the guard."
        )


def _compression_lock_holder_process_is_dead(holder: str) -> bool:
    """True only when a ``pid=<n>`` lock holder's local PID is provably gone.
    Reclaim on kernel proof only: unstructured/same-process holders (another
    thread's live lease) and any probe doubt keep the lease until TTL expiry
    (PID reuse must never steal a live lease; a wrongly-kept one self-heals).
    Foreign/unstamped PID namespaces defer to TTL: see ``hermes_state_pidns``."""
    match = re.search(r"(?:^|:)pid=(\d+)(?::|$)", holder or "")
    pid = int(match.group(1)) if match else 0
    if pid <= 0 or pid == os.getpid():
        return False
    if not holder_pid_checkable(holder):
        return False  # foreign / unknown namespace: defer to TTL
    if psutil is not None:
        try:
            return not psutil.pid_exists(pid)  # recycled PIDs read as alive (conservative)
        except Exception:
            return False
    # psutil-less fallback is POSIX-only: on Windows os.kill(pid, 0) maps sig=0 to
    # CTRL_C_EVENT and can kill the target's console group.
    if os.name == "nt":
        return False
    try:
        os.kill(pid, 0)  # windows-footgun: ok — nt early-returns just above
    except ProcessLookupError:
        return True
    except (OSError, OverflowError):  # PermissionError is an OSError: alive but foreign
        return False
    return False


# Billing buckets that aren't a routable provider identity: a session that persisted only
# one of these (never ran /model) falls back to the config default. Shared by
# session_gateway_runtime and tui_gateway.server so they cannot drift.
_BARE_BILLING_PROVIDERS = frozenset({"auto", "custom"})

T = TypeVar("T")

# Import-time snapshot lets _default_db_path() detect a re-pointed DEFAULT_DB_PATH
# (tests monkeypatch the constant directly).
DEFAULT_DB_PATH = _IMPORT_DEFAULT_DB_PATH = get_hermes_home() / "state.db"

# Back off from read-only opens after one fails: not per query, but short enough that
# transient fd pressure doesn't strand the read pool.
# Transient SQLITE_IOERR retry budget for READ-ONLY opens (#100436): a WAL writer's checkpoint/
# reset/frame flush surfaces "disk I/O error" to a concurrent mode=ro reader for a millisecond-
# wide window — the ro connection cannot perform WAL recovery because recovery writes the -shm
# index, which mode=ro refuses. The writer closes the window on its own, so a few short retries
# make the open succeed instead of 500-ing the whole /api/sessions poll (or any other ro opener).
# Deliberately NOT for writable opens: a writer owns the transition, so an IOERR there is a real
# storage/fd problem. A persistent IOERR still exhausts the budget and propagates.
_READ_ONLY_IOERR_RETRY_ATTEMPTS, _READ_ONLY_IOERR_RETRY_BACKOFF_S = 3, 0.05
# SQLite busy handler budget for reads. Under DELETE (rollback-journal) mode a reader needs a SHARED
# lock, which every commit from another process blocks across its journal+db fsyncs; the writer
# connection's 1 s timeout exists for writes (they retry at application level) and starved readers
# into "database is locked" (dashboard 503s, `hermes sessions list` crashes) under a busy gateway.
_READ_BUSY_TIMEOUT_S = 5.0


def _default_db_path() -> Path:
    """Default state DB path at CALL time: a re-pointed ``DEFAULT_DB_PATH`` wins, else
    ``get_hermes_home()`` is resolved fresh (a runtime HERMES_HOME redirect works regardless of import)."""
    return DEFAULT_DB_PATH if DEFAULT_DB_PATH != _IMPORT_DEFAULT_DB_PATH else get_hermes_home() / "state.db"


# Live-DB guard knobs live HERE (not in hermes_state_guard): the hermetic conftest monkeypatches
# ``hermes_state._STATE_DB_GUARD_BYPASS`` (``@pytest.mark.live_system_guard_bypass`` escape hatch)
# and ``_EXTRA_DENY_ROOTS`` (the pre-sandbox root, so custom-HERMES_HOME deployments are covered).
_STATE_DB_GUARD_BYPASS = False
_STATE_DB_GUARD_EXTRA_DENY_ROOTS: tuple[Path, ...] = ()


def _ensure_test_isolation(db_path: Path) -> None:
    """Raise before any connection/mkdir/pragma/byte probe when a pytest-context process
    (env OR ancestry) resolves a production DB.

    Env alone is not enough: a child spawned with a rebuilt environment loses ``PYTEST_*`` and
    ``HERMES_HOME`` together, which is precisely the state in which it writes to production (#82770).
    """
    if _STATE_DB_GUARD_BYPASS or os.environ.get(_STATE_DB_GUARD_BYPASS_ENV) or not _in_test_context():
        return
    try:
        resolved = Path(db_path).expanduser().resolve()
    except Exception:
        return
    roots = [r for r in (_real_platform_state_root(),) if r is not None]
    for extra in _STATE_DB_GUARD_EXTRA_DENY_ROOTS:
        try:
            roots.append(Path(extra).expanduser().resolve())
        except Exception:
            continue
    for root in roots:
        if _is_production_state_db(resolved, root):
            raise RuntimeError(
                "live-system guard: test attempted to open production "
                f"state.db at {resolved} (under real Hermes root {root}). "
                "Tests must run against a temporary HERMES_HOME — pass an "
                "explicit tmp db_path or let the hermetic conftest redirect "
                "HERMES_HOME. If this test genuinely needs the live database, mark it with "
                "@pytest.mark.live_system_guard_bypass — or, for a spawned "
                f"child process, export {_STATE_DB_GUARD_BYPASS_ENV}=1 in "
                "its environment."
            )




# Openings of the background-review harness prompts (agent/background_review.py).






# Matches a bare protocol/tool-name marker such as "[memory]" or "[skill_manage]".






_SESSION_DB_CONSEQUENCE = "Sessions will not be saved until this is fixed."
_NETWORK_DRIVE_HINT = " If the database lives on a network drive, move it to a local disk."
_NETWORK_DRIVE_GLOSS = "the session database could not be opened; it may be on a network or unsupported drive"
_NETWORK_DRIVE_ACTION = (
    "Move it to a local disk (`hermes {profile_arg}doctor` shows where it is), then start Hermes again."
)


def format_session_db_unavailable(
    prefix: str = "Hermes can't open its session history right now",
    *,
    details: bool = False,
) -> str:
    """User-facing one-liner: ``<prefix>: <gloss>. <consequence> <action>[ network hint]``.

    The cause table lives in ``hermes_state_user_copy`` so CLI, gateway and TUI agree. Chat
    surfaces (gateway, TUI) get the one-liner; ``details=True`` (the CLI banner) appends a
    ``Details: <raw cause>`` line for the raw SQLite text. Network filesystems (NFS/SMB/FUSE/ZFS)
    cannot host SQLite's write-ahead log: when the raw cause carries one of those markers the
    message names the network-drive suspicion, because ``hermes doctor --fix`` cannot repair a
    mount — only moving the file can."""
    from hermes_constants import profile_cli_selector

    profile_arg = profile_cli_selector()
    cause = get_last_init_error()
    if not cause:
        return (
            f"{prefix}. {_SESSION_DB_CONSEQUENCE} Run `hermes {profile_arg}doctor` to check the "
            "storage location."
        )
    from hermes_state_user_copy import describe_storage_failure
    failure = describe_storage_failure(cause)
    gloss, action, hint = failure.gloss, failure.action, ""
    if any(m in cause.lower() for m in _WAL_INCOMPAT_MARKERS):
        if failure.cause == "unknown":
            gloss, action = _NETWORK_DRIVE_GLOSS, _NETWORK_DRIVE_ACTION.replace("{profile_arg}", profile_arg)
        else:
            hint = _NETWORK_DRIVE_HINT
    text = f"{prefix}: {gloss}. {_SESSION_DB_CONSEQUENCE} {action}{hint}"
    if details:
        from hermes_state_user_copy import storage_failure_details
        text += f"\nDetails: {storage_failure_details(cause)}"
    return text


# Auto-repair at most once per DB path per process (no repair loops; serialises concurrent
# web_server / gateway opens on the same malformed file).
_repair_attempted_paths: set[str] = set()
_repair_attempt_lock = threading.Lock()
# Cross-process schema-surgery lock timeout (``_repair_attempt_lock`` covers one interpreter
# only); sized for the slowest legitimate holder (VACUUM, multi-GB DB).
_REPAIR_LOCK_TIMEOUT_SECONDS = 120.0
_IS_WINDOWS = sys.platform == "win32"




def divert_session_transcript_jsonl(session_id: str, messages) -> Optional[Path]:
    """Append pending messages to HERMES_HOME/sessions/<id>.jsonl (state.db was replaced under a
    live process). Returns the path, or None if nothing to write."""
    sid = str(session_id or "").strip()
    if not sid or not messages:
        return None
    sessions_dir = get_hermes_home() / "sessions"
    make_user_dir(sessions_dir, parents=True, exist_ok=True)
    path = sessions_dir / f"{sid}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for msg in messages:
            if msg is not None:
                record = msg if isinstance(msg, dict) else {"content": str(msg)}
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


# Process-wide shared SessionDB registry: long-lived in-process callers share ONE writer
# connection per resolved path via hermes_state_registry.acquire(); one-shots use SessionDB() + close().
def _foreign_state_db_holders(db_path: Path) -> list[tuple[int, str]]:
    """Compatibility delegate to the state-holder authority."""
    return _state_holders.foreign_state_db_holders(db_path)


# ── Process-wide shared SessionDB registry (#90837) ── lives in hermes_state_registry.py (acquire /
# release / close_all / release_or_close). Long-lived in-process callers (gateway, tui_gateway, cron,
# in-process tools) share ONE writer connection per resolved path via hermes_state_registry.acquire(); CLI
# one-shots, recovery flows, and read-only cross-profile opens use SessionDB() directly with their own close().


class SessionDB(
    SessionSessionsMixin, SessionFtsSetupMixin, SessionSearchMixin, SessionSchemaMixin,
    SessionPortabilityMixin, SessionTelegramTopicsMixin, SessionCompressionMixin,
    SessionGatewayMixin, SessionMaintenanceMixin, SessionUsageMixin, SessionTitlesMixin,
    SessionMessagesMixin, SessionPruneRewriteMixin, SessionApiContentMixin, SessionCoverageMixin, SessionRewindMixin,
    SessionPromptRefreshMixin,
):
    """SQLite-backed session storage with FTS5 search; many reader threads, one writer (WAL)."""

    # Only these state-owned producers join automatic stale-open reconciliation; messaging/UI
    # sources have their own lifecycle owners; unknown sources fail closed.
    # See #60609.  `recovered` = placeholders `hermes sessions recover` synthesizes for
    # orphaned messages (no live owner, never stamped ended_at); without it they are immortal.
    _AUTO_PRUNE_STALE_OPEN_SOURCES: tuple[str, ...] = AUTO_PRUNE_STALE_OPEN_SOURCES

    # ── Write-contention tuning ──
    # SQLite's deterministic busy handler convoys under many hermes processes: keep its
    # timeout short (1s) and retry with random jitter. Patience is TIME-based (a sibling
    # legitimately holds the lock for seconds: checkpoint at close, VACUUM, recovery, FTS
    # optimize); attempt-counted budgets destroyed turns on a healthy store. Transcript
    # writes (failure aborts the turn) get the long budget; observation-only activity
    # writes sit on the response-critical path and get a sub-second one.
    _WRITE_PATIENCE_S, _TRANSCRIPT_WRITE_PATIENCE_S, _ACTIVITY_WRITE_PATIENCE_S = 20.0, 60.0, 0.5
    # A live compression lock gets a short wait (compression publishes in seconds), but the lease
    # is a correctness boundary: a writer still locked out afterwards is refused.
    # Observation-only activity heartbeat/label writes (#76354 review S1): these run on (or adjacent to) the
    # response-critical path and must never wait out the full routine patience under contention. Sub-second
    # budget; a skipped write is retried naturally at the next heartbeat window.
    # A live compression lock gets its own, much shorter budget than the write lock. Compression publishes
    # in a couple of seconds, so a brief wait saves the overwhelming majority of concurrent turns (#75083).
    # It deliberately stays short: the lease is a correctness boundary, not just a busy signal (see
    # test_compression_lease_blocks_non_owner_but_allows_owner_flush), so a writer that is still locked out
    # after this budget must still be refused rather than allowed to land a stale turn in a session whose
    # compression is genuinely long-running or wedged.
    _COMPRESSION_BUSY_WAIT_S = 5.0
    _WRITE_RETRY_MIN_S, _WRITE_RETRY_MAX_S = 0.020, 0.150  # fast jitter for the first _SLOW_AFTER_S
    _WRITE_RETRY_SLOW_AFTER_S = 2.0
    _WRITE_RETRY_SLOW_MIN_S, _WRITE_RETRY_SLOW_MAX_S = 0.250, 1.000
    # PASSIVE WAL checkpoint every N successful writes.
    _CHECKPOINT_EVERY_N_WRITES = 50
    # Bounded FTS ``'merge'`` (ms of lock each) instead of ``'optimize'`` (9-18s per index on a 10GB
    # DB, longer than a writer's patience); up to _COMMANDS_PER_PASS per index, stopping on no-progress.
    _FTS_MERGE_EVERY_N_WRITES, _FTS_MERGE_MAX_PAGES_PER_INDEX, _FTS_MERGE_COMMANDS_PER_PASS = 1000, 500, 4
    # Imports cap lower than exports: an import holds one BEGIN IMMEDIATE.
    _IMPORT_MAX_SESSIONS, _IMPORT_MAX_MESSAGES_PER_SESSION, _IMPORT_MAX_TOTAL_MESSAGES = 500, 10_000, 50_000
    _IMPORT_MAX_SESSION_BYTES, _IMPORT_MAX_TOTAL_BYTES = 5 * 1024 * 1024, 25 * 1024 * 1024
    # Accounting workers retire when idle so a bound-method target can't keep an abandoned SessionDB alive.
    _TOKEN_WRITER_IDLE_SECONDS = 30.0

    @property
    def runtime(self):
        from hermes_cli.db_sessions import sqlite_runtime_for_store
        return sqlite_runtime_for_store(self)

    @staticmethod
    def _store_system_prompt(conn, system_prompt: Optional[str]) -> Optional[str]:
        if system_prompt is None:
            return None
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT OR IGNORE INTO system_prompts (hash, prompt) VALUES (?, ?)",
            (prompt_hash, system_prompt),
        )
        return prompt_hash

    @staticmethod
    def _delete_unreferenced_system_prompts(conn) -> None:
        conn.execute(
            "DELETE FROM system_prompts WHERE NOT EXISTS ("
            "SELECT 1 FROM sessions WHERE sessions.system_prompt_hash = system_prompts.hash) AND NOT EXISTS ("
            "SELECT 1 FROM sessions WHERE sessions.tool_names = system_prompts.hash)"
        )

    @staticmethod
    def _session_row_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for column in ("system_prompt", "tool_names"):
            if f"_{column}_resolved" in data:
                resolved = data.pop(f"_{column}_resolved")
                if column in data:
                    data[column] = resolved
        # Lift /new vs /branch markers out of model_config so list payloads
        # (which strip that heavy field) can still tell a reset sibling from
        # a genuine fork. Keep this a local helper: tests sometimes replace
        # the SessionDB name with a factory lambda.
        if not (data.get("_reset_from") and data.get("_branched_from")):
            raw = data.get("model_config")
            cfg = None
            if isinstance(raw, str) and raw:
                try:
                    cfg = json.loads(raw)
                except (TypeError, ValueError):
                    cfg = None
            elif isinstance(raw, dict):
                cfg = raw
            if isinstance(cfg, dict):
                if not data.get("_reset_from"):
                    value = cfg.get("_reset_from")
                    if isinstance(value, str) and value.strip():
                        data["_reset_from"] = value.strip()
                if not data.get("_branched_from"):
                    value = cfg.get("_branched_from")
                    if isinstance(value, str) and value.strip():
                        data["_branched_from"] = value.strip()
        return data



    def __init__(self, db_path: Path | None = None, read_only: bool = False):
        """Explicitly create or upgrade a writer, or inspect a store for recovery."""
        opener = self._open_read_only if read_only else self._open_writer
        path = db_path or _default_db_path()
        _ensure_test_isolation(path)
        self._initialize(path, read_only, opener)

    @classmethod
    def open_existing(cls, db_path: Path | None = None, read_only: bool = False):
        """Open an initialized store without creating or migrating its schema."""
        from hermes_db.errors import StorageSchemaError

        path = db_path or _default_db_path()
        _ensure_test_isolation(path)
        if not path.is_file():
            message = "Session store is missing. Run `hermes db upgrade` for this profile."
            _set_last_init_error(message)
            raise StorageSchemaError(message)
        db = cls.__new__(cls)
        db._initialize(path, read_only, db._open_existing)
        return db

    def _initialize(self, db_path, read_only, opener):
        self.db_path = db_path
        self.read_only = read_only
        # Keep only the opening call site, never a frame (which pins caller locals).
        try:
            caller = sys._getframe(1).f_back
        except PermissionError:
            # A host audit hook may deny frame diagnostics without denying storage.
            caller = None
        self._creation_site = (
            f"{caller.f_globals.get('__name__', '?')}.{caller.f_code.co_name}:{caller.f_lineno}"
            if caller is not None else "unknown"
        )
        del caller
        self._connections = SQLiteConnections(
            self.db_path, read_only=read_only, read_uri=read_only_db_uri(self.db_path),
            pragmas=capture_database_pragmas(), creation_site=self._creation_site,
            capture_retired=db_session_schema.capture_retired_wal_generation,
            replaced_message=_STATE_DB_REPLACED_MSG, deleted_message=_DELETED_WAL_GENERATION_MSG,
        )
        self._write_count = 0
        self._fts_usermerge_floor_applied = False  # one-shot usermerge-floor write guard
        self._fts_enabled = self._fts_stale = self._trigram_available = False
        self._fts_unavailable_warned = False
        # Async token accounting; distinct from self._connections._lock so enqueue/flush never contends with writes.
        self._token_queue: deque = deque()
        self._token_queue_cond = threading.Condition(threading.Lock())
        self._token_writer_thread: Optional[threading.Thread] = None
        self._token_writer_stop = self._token_writer_busy = False
        self._token_atexit_hook: Optional[Callable[[], None]] = None
        # Opened via hermes_state_registry.acquire(): close() releases a refcount instead.
        # Set True when this instance is opened via hermes_state_registry.acquire(). Makes close() a no-op so the
        # registry (not individual callers) controls the connection lifecycle (#90837).
        self._shared_registry_owned = False
        initialization_complete = False
        try:
            opener()
            identity_error = self._connections._record_db_file_identity(
                read_attempts=_READ_ONLY_IOERR_RETRY_ATTEMPTS,
                read_backoff=_READ_ONLY_IOERR_RETRY_BACKOFF_S,
            )
            if identity_error is not None:
                note_storage_error(self.db_path, identity_error)
            initialization_complete = True
        except Exception as exc:
            # Surface WHY via /resume and friends; callers keep their ``_session_db = None`` path.
            _set_last_init_error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if not initialization_complete:
                conn, self._connections._conn = self._connections._conn, None
                self._connections._close_connection_quietly(conn)
            else:
                # Only a successfully opened handle owns a writer connection. Failed
                # construction must not leave a diagnostic member behind.
                self._connections.attach_writer(self._connections._conn, wal_active=self._connections._wal_active)
                # Test-isolation runs only (gated inside the helper): register
                # for the suite-level leak sweep in tests/conftest.py.
                _register_test_instance(self)

    def _open_existing(self) -> None:
        try:
            if self.read_only:
                self._open_read_only(self._check_existing_schema)
                return
            preflight_db_writability(self.db_path, db_label="state.db")
            refuse_deleted_wal_generation(self.db_path, message=_DELETED_WAL_GENERATION_MSG)
            self._connections._conn = conn = self._connections.connect_existing_writer()
            self._check_existing_schema(conn)
            self._probe_readable_fts(conn.cursor())
            db_session_schema.configure_session_writer(self._connections, conn)
        except sqlite3.DatabaseError as exc:
            if note_storage_error(self.db_path, exc) or is_malformed_db_error(exc):
                raise StateDbCorruptError(
                    "Session store database disk image is malformed. Run `hermes doctor` for this profile."
                ) from exc
            raise
        self._ensure_db_file_generation()
        self._connections.hold_wal_guard()

    def _open_writer(self) -> None:
        """Writable open: preflight, zero-byte quarantine, connect + schema (one in-place repair of a
        malformed sqlite_master), generation stamp."""
        # Never materialize a deleted/archived named profile's home: a multiplexer or Desktop backend
        # still holding the profile's route would otherwise re-scaffold it on the next turn (#94590).
        self._connections.prepare_writer()
        mkdir_under_hermes_home(self.db_path.parent)
        try:
            # Serialize zero-byte check, quarantine, connect and schema commit so concurrent
            # openers don't race the absent-path -> schema-commit window.
            if not self.db_path.exists() or db_session_schema.has_invalid_sqlite_header_preopen(self.db_path):
                # The directory must be writable before the lock file can be created in it; the
                # directory never vanishes mid-quarantine, so checking it unlocked is race-free.
                preflight_db_writability(self.db_path, db_label="state.db", directory_only=True)
                with db_session_schema.quarantine_cross_process_lock(self.db_path) as lock_acquired:
                    if not lock_acquired:
                        logger.warning(
                            "startup quarantine lock for %s not acquired within 5s; proceeding",
                            self.db_path,
                        )
                    # Preflight under the lock: unlocked, it can list state.db just before a
                    # concurrent opener renames it aside, and os.access on the vanished path
                    # then reports a writable DB as "read-only for this user".
                    preflight_db_writability(self.db_path, db_label="state.db")
                    self._handle_quarantine_if_invalid(already_locked=lock_acquired)
                    self._connect_and_init_with_lock_patience()
            else:
                # Read-only file/sidecar preflight BEFORE the first connection: an actionable message
                # instead of an opaque "attempt to write a readonly database" from inside _init_schema.
                preflight_db_writability(self.db_path, db_label="state.db")
                self._handle_quarantine_if_invalid(already_locked=False)
                self._connect_and_init_with_lock_patience()
        except sqlite3.DatabaseError as exc:
            # A malformed schema fails on the very first statement (before _init_schema), so the
            # FTS-rebuild layer never sees it: repair sqlite_master in place (backup first), reopen once.
            if not is_malformed_schema_error(exc) or not _claim_repair_attempt(self.db_path):
                raise
            logger.error(
                "state.db schema is malformed (%s) — attempting automatic "
                "repair (a backup copy is made first).", exc,
            )
            self._connections._close_connection_quietly(self._connections._conn)
            if not repair_state_db_schema(self.db_path).get("repaired"):
                raise
            self._connect_and_init_with_lock_patience()
        # FTS optimization is OPT-IN (`hermes db optimize`); no background worker races session lifecycle.
        self._ensure_db_file_generation()
        self._connections.hold_wal_guard()

    def _open_read_only(self, check_schema=None) -> None:
        """Read-only attach for cross-profile aggregation: no schema init, NO write
        lock (sidebar polling never contends with that profile's backend); the DB
        must exist. FTS flags are probed with SELECTs only, and the connection is
        closed on any probe failure so it cannot block an explicit repair."""
        for attempt in range(_READ_ONLY_IOERR_RETRY_ATTEMPTS + 1):
            try:
                self._connections._conn = conn = self._connections._connect_read_only(timeout=_READ_BUSY_TIMEOUT_S)
                try:
                    apply_database_pragmas(conn, db_label="state.db")
                    if check_schema is not None:
                        check_schema(conn)
                    self._probe_readable_fts(conn.cursor())
                except BaseException:
                    self._connections._conn = None
                    self._connections._close_connection_quietly(conn)
                    raise
                return
            except sqlite3.OperationalError as ioerr:
                # In-flight WAL checkpoint/reset/frame-flush on the writer side can surface
                # SQLITE_IOERR to a mode=ro reader (it can't do the -shm recovery the read
                # needs). Closes in milliseconds: retry a bounded number of times before
                # classifying the store as failed (#100436; see _READ_ONLY_IOERR_RETRY_ATTEMPTS).
                # A lock is NOT retried here: the connection already waited _READ_BUSY_TIMEOUT_S,
                # and a retry would multiply that wait on blocking callers (TUI, `hermes status`).
                transient = _DISK_IO_ERROR_MARKER in str(ioerr).lower()
                if attempt >= _READ_ONLY_IOERR_RETRY_ATTEMPTS or not transient:
                    raise
                time.sleep(_READ_ONLY_IOERR_RETRY_BACKOFF_S)


    def _handle_quarantine_if_invalid(self, already_locked: bool = False) -> None:
        """Quarantine a zero-byte/headerless state.db so a fresh one can open; if quarantine failed,
        raise the clear message instead of opening the zeroed file."""
        if not (self.db_path.exists() and db_session_schema.has_invalid_sqlite_header_preopen(self.db_path)):
            return
        try:
            zsize = self.db_path.stat().st_size
        except OSError:
            zsize = -1
        qpath = db_session_schema.quarantine_invalid_state_db(self.db_path, already_locked=already_locked)
        where = f"moved aside to {qpath}" if qpath else "left in place (it could not be moved aside)"
        msg = (
            f"state.db was empty or damaged ({zsize} bytes) and has been {where}; Hermes started with a "
            "fresh, empty session database. To bring old sessions back, run "
            f"`hermes sessions recover --source {qpath or self.db_path} --inspect-only`, or restore a "
            "snapshot with `/snapshot list` then `/snapshot restore <id>` (terminal `hermes` chat only)."
        )
        logger.error(msg)
        _set_last_init_error(msg)
        if qpath is None and self.db_path.exists() and db_session_schema.has_invalid_sqlite_header_preopen(self.db_path):
            raise sqlite3.DatabaseError(msg)


    def _connect_and_init(self) -> None:
        # Refuse before sqlite3.connect (under the startup lock) so we cannot mint
        # a replacement WAL while a live writer still holds a deleted sidecar inode.
        refuse_deleted_wal_generation(self.db_path, message=_DELETED_WAL_GENERATION_MSG)
        # Create/tighten the main database before sqlite3.connect() so a
        # permissive process umask can never expose a fresh profile store.
        _secure_state_db_files(self.db_path, create_main=True)
        self._connections._conn = db_session_schema.open_session_writer(self._connections)
        self._init_schema()

    def _connect_and_init_with_lock_patience(self) -> None:
        """Open + init, waiting out a sibling's write lock with jittered patience:
        _init_schema's DDL runs on a 1s-timeout connection, so a sibling's VACUUM
        or checkpoint used to fail the ENTIRE open and callers disabled
        persistence for the whole run. Non-lock errors propagate immediately."""
        # Lock contention during open: _init_schema's DDL/reconcile statements run on a 1s-timeout
        # connection with no retry, so a sibling process holding the write lock (VACUUM, TRUNCATE checkpoint
        # at close, a long FTS pass from an older still-running install) used to fail the ENTIRE open —
        # callers then disable persistence for the whole run ("Failed to initialize SessionDB ... database
        # is locked", #74478). The store is healthy; wait it out with the same jittered patience the write
        # path uses.
        deadline = time.monotonic() + self._WRITE_PATIENCE_S
        while True:
            try:
                self._connect_and_init()
                return
            except sqlite3.OperationalError as exc:
                if not is_sqlite_lock_error(exc):
                    raise
                self._connections._close_connection_quietly(self._connections._conn)
                now = time.monotonic()
                if now >= deadline:
                    log_write_lock_holders(self.db_path, self._WRITE_PATIENCE_S)
                    raise
                jitter = random.uniform(self._WRITE_RETRY_SLOW_MIN_S, self._WRITE_RETRY_SLOW_MAX_S)
                time.sleep(min(jitter, max(deadline - now, 0.001)))

    # ── Read-path split ──





    @contextmanager
    def _read_ctx(self, *, reopen: bool = True, pooled_only: bool = False) -> Iterator[sqlite3.Connection]:
        """Yield a connection for read-only statements: a pooled read-only
        connection with NO lock under WAL; otherwise (non-WAL, open failure,
        ceiling reached) the writer connection under self._connections._lock — deliberate
        degradation: slower beats EMFILE, which the supervisor cannot see.
        ``reopen=False``: a read after ``close()`` raises instead of reopening the
        writer (an optional reader must not hold a home that is being deleted). Inside this thread's
        ``transcript_read_snapshot``: its connection, so every read there sees one generation.
        ``pooled_only``: None instead of the writer connection when no pooled reader is available."""
        pinned = self._pinned_read_conn()
        if pinned is not None:
            yield pinned
            return
        with self._connections.pooled_read() as conn:
            if conn is not None:
                yield conn
                return
        if pooled_only:
            yield None
            return
        with self._connections._lock:
            if self._connections._conn is None:  # close() raced a still-unwinding reader
                if not reopen:
                    raise sqlite3.ProgrammingError(f"SessionDB for {self.db_path} is closed")
                self._reopen_after_close_locked(context="read")
            with self._connections.read_locked_writer() as conn:
                yield conn

    def _reopen_after_close_locked(self, context: str = "write") -> None:
        """Reopen the writer after ``close()`` raced a live caller (a teardown owner
        set ``_conn = None`` while a worker still had a transcript flush to land).
        Loud (WARNING) and bounded (only after an explicit close()). Caller holds
        ``self._connections._lock``. No _init_schema: no DDL races with siblings during teardown."""
        if self.read_only:
            raise sqlite3.ProgrammingError(
                f"SessionDB for {self.db_path} was closed (read-only handle); "
                f"cannot serve a {context} after close()"
            )
        # A reopen resolves the PATH again: a replaced file would be written through stale WAL/shm
        # assumptions; a quarantined handle must never hand a fresh connection to a damaged file.
        if self._connections._db_corrupt and not (self._connections._db_replaced or self._connections._db_file_was_replaced()):
            raise self._corrupt_error(
                f"state.db connection for {self.db_path} is quarantined after "
                f"structural corruption; refusing to reopen for a {context} "
                "after close(). "
            )
        self._connections._halt_if_db_generation_changed()
        logger.warning(
            "state.db connection for %s was closed while a %s was still in "
            "flight — reopening (teardown/worker race, #94736)", self.db_path, context,
        )
        try:
            self._connections._conn = conn = self._connections.connect_existing_writer()
            try:
                db_session_schema.configure_session_writer(self._connections, conn)
            except BaseException:
                self._connections._conn = None
                self._connections._close_connection_quietly(conn)
                raise
        except Exception as exc:
            raise sqlite3.OperationalError(
                f"state.db connection was closed while a {context} was still "
                f"in flight (a session-teardown path called close() before "
                f"this worker finished — #94736) and the automatic reopen failed: {exc}"
            ) from exc
        self._connections.hold_wal_guard()

    def _execute_write(
        self, fn: Callable[[sqlite3.Connection], T], patience_s: Optional[float] = None,
    ) -> T:
        """Run *fn(conn)* inside BEGIN IMMEDIATE with jittered lock retry; commit
        is handled here (callers must not commit). Returns *fn*'s result.
        BEGIN IMMEDIATE takes the WAL write lock up front so contention surfaces
        immediately; on locked/busy the Python lock is released, a jitter slept,
        and the WHOLE callback retried — *fn* must stay idempotent under retry."""
        if patience_s is None:
            patience_s = self._WRITE_PATIENCE_S
        deadline = time.monotonic() + patience_s
        compression_deadline: Optional[float] = None  # set on the first compression-busy collision
        # One retry for SQLITE_IOERR raised by BEGIN IMMEDIATE itself (callback not run: nothing
        # replayed). Once fn has started, an IOERR leaves settlement unknown and must propagate.
        # The callback has not run at that point, so there is no durable effect to replay and the retry is
        # exactly-once safe (#99502's contract). Once the callback starts, an IOERR leaves the write's
        # settlement unknown and must propagate — this helper owns non-idempotent transcript/counter
        # mutations, not just idempotent UPSERTs.
        ioerr_begin_retried = False
        while True:
            self._raise_if_db_corrupt(storage=True)
            # NOTE: the replaced/generation live probe runs INSIDE the lock below,
            # not here. close() mutates _conn and _db_sidecar_identity under that
            # same lock, ending the WAL generation (SQLite unlinks the -wal/-shm
            # sidecars on a clean close). A lock-free probe that races close() can
            # observe the mid-teardown state — sidecars already unlinked while
            # _db_sidecar_identity is not yet cleared — and misclassify this
            # process's OWN clean close as an externally deleted generation,
            # raising a sticky DeletedWalGenerationError that permanently refuses
            # later writes (#105567). Inside the lock the probe only ever sees the
            # stable post-close state (identity cleared → adopt / reopen path).
            fn_started = False
            try:
                with self._connections._lock:
                    self._connections._raise_if_db_replaced()
                    if self._connections._conn is None:  # close() raced this writer
                        self._reopen_after_close_locked(context="write")
                    with self._connections.write_transaction() as conn:
                        fn_started = True
                        result = fn(conn)
                # Success — periodic best-effort checkpoint + FTS merge.
                self._write_count += 1
                if self._write_count % self._CHECKPOINT_EVERY_N_WRITES == 0:
                    self._connections._try_wal_checkpoint()
                if self._write_count % self._FTS_MERGE_EVERY_N_WRITES == 0:
                    self._try_incremental_merge_fts()
                return result
            except SessionCompressionInProgressError:
                # Transient (see _COMPRESSION_BUSY_WAIT_S): a steer landing mid-compression must not abort.
                # A live foreign compression lock is transient: the compressor publishes in a couple of
                # seconds. Without any wait, a steer that lands mid-compression aborts the user's turn as
                # session_persistence_failed and sends the operator hunting disk space that was never the
                # problem (#75083). The budget is _COMPRESSION_BUSY_WAIT_S, not the write-lock patience: the
                # lease is a correctness boundary, so a writer still locked out after a short wait must be
                # refused rather than left to land a stale turn once a long-running or wedged compression
                # finally lets go.
                if compression_deadline is None:
                    compression_deadline = min(time.monotonic() + self._COMPRESSION_BUSY_WAIT_S, deadline)
                if self._sleep_before_write_retry(
                    compression_deadline, self._COMPRESSION_BUSY_WAIT_S
                ):
                    continue
                raise
            except sqlite3.Error as exc:
                # 'no more rows' is a transient engine error on contended WAL appends (some builds
                # raise it as InterfaceError, a sibling of DatabaseError): retry like locked/busy.
                if _is_no_more_rows(exc) and self._sleep_before_write_retry(deadline, patience_s):
                    continue
                err_msg = str(exc).lower()
                if isinstance(exc, sqlite3.OperationalError):
                    if is_sqlite_lock_error(exc):
                        if self._sleep_before_write_retry(deadline, patience_s):
                            continue
                        # Say what actually happened, not disk/permission damage. The holder goes to
                        # the log, not the message: classify_persistence_error() buckets by phrase and
                        # a holder's argv (a worktree named fix-corrupt-db) would flip the bucket.
                        log_write_lock_holders(self.db_path, patience_s)
                        raise sqlite3.OperationalError(
                            f"database is locked (another Hermes process held the "
                            f"state.db write lock for over {patience_s:.0f}s — "
                            "likely a long maintenance operation such as VACUUM, "
                            "a large WAL checkpoint, or an older pre-update "
                            "process; the database itself is healthy)"
                        ) from exc
                    if (
                        _DISK_IO_ERROR_MARKER in err_msg and not fn_started and not ioerr_begin_retried
                        and self._sleep_before_write_retry(deadline, patience_s)
                    ):
                        # Retry on the SAME connection: close()+reopen would cancel this process's
                        # POSIX locks for every sibling (howtocorrupt §2.2).
                        ioerr_begin_retried = True
                        continue
                    raise  # non-lock error, callback already ran, or patience exhausted
                if isinstance(exc, sqlite3.DatabaseError):
                    # An out-of-band replace surfaces as this same corruption class; in-file repair
                    # on a NEW generation amplifies the damage.
                    if (
                        "not a database" in err_msg or is_malformed_db_error(exc)
                        or self._is_fts_write_corruption_error(exc)
                    ):
                        with self._connections._lock:
                            self._connections._raise_if_db_replaced()
                    # Corrupt FTS shadow tables fail every write via the sync triggers while canonical
                    # rows are intact: detach the derived indexes atomically and retry (never rebuild here).
                    if self._enter_fts_fail_open(exc, deadline=deadline, patience_s=patience_s):
                        continue
                    # What survives both checks is structural damage: quarantine.
                    if self._is_structural_corruption_error(exc):
                        self._halt_db_corrupt(exc)
                raise

    def _write_sql(
        self, sql: str, params: Any = (), *, many: bool = False, patience_s: Optional[float] = None,
    ) -> None:
        """Run one INSERT/UPDATE/DELETE through ``_execute_write``."""
        def _do(conn):
            (conn.executemany if many else conn.execute)(sql, params)
        self._execute_write(_do, patience_s=patience_s)

    def _write_rowcount(self, sql: str, params: Any = (), *, patience_s: Optional[float] = None) -> int:
        """Run one UPDATE/DELETE through ``_execute_write``; return rows changed
        (``SELECT changes()`` when the driver reports None / negative)."""
        def _do(conn):
            rowcount = conn.execute(sql, params).rowcount
            if rowcount is None or rowcount < 0:
                rowcount = conn.execute("SELECT changes()").fetchone()[0]
            return rowcount
        return self._execute_write(_do, patience_s=patience_s)

    def _read_one(self, sql: str, params: Any = ()) -> Optional[sqlite3.Row]:
        """``fetchone()`` of one read-only statement via ``_read_ctx``."""
        return self._read_retrying_ioerr(lambda conn: conn.execute(sql, params).fetchone())

    def _read_all(self, sql: str, params: Any = ()) -> list[sqlite3.Row]:
        """``fetchall()`` of one read-only statement via ``_read_ctx``."""
        return self._read_retrying_ioerr(lambda conn: conn.execute(sql, params).fetchall())

    def _read_retrying_ioerr(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run an idempotent SELECT through ``_read_ctx``, retrying a transient SQLITE_IOERR.

        A warm ``mode=ro`` pooled reader can hit the same millisecond-wide WAL transition window as a
        read-only OPEN (#100436) when its statement executes or steps: a sibling process's checkpoint /
        WAL reset / frame flush surfaces ``disk I/O error`` because a read-only connection cannot rewrite
        the -shm index (#100871, WSL2 ext4-on-vhdx, multi-process). The window closes on its own, so
        the statement is replayed on the SAME connection within the read-only IOERR budget -- never
        closed and reopened (close() cancels this process's POSIX locks for every sibling connection),
        never quarantined (busy is not broken). A persistent IOERR exhausts the budget and propagates."""
        for attempt in range(_READ_ONLY_IOERR_RETRY_ATTEMPTS + 1):
            try:
                with self._read_ctx() as conn:
                    return fn(conn)
            except sqlite3.OperationalError as exc:
                if attempt >= _READ_ONLY_IOERR_RETRY_ATTEMPTS or _DISK_IO_ERROR_MARKER not in str(exc).lower():
                    note_storage_error(self.db_path, exc)
                    raise
                time.sleep(_READ_ONLY_IOERR_RETRY_BACKOFF_S)
            except sqlite3.DatabaseError as exc:
                # A reader is often the only observer (the sidebar poll on a store nobody is
                # writing to): publish structural damage so the list is not read as empty.
                note_storage_error(self.db_path, exc)
                raise

    def _ensure_db_file_generation(self) -> None:
        """Mint a once-per-file generation stamp (state_meta + application_id). First opener wins (INSERT
        OR IGNORE); application_id is written only while 0 so racers converge. PASSIVE checkpoint only.

        See #45383.
        """
        if self.read_only or self._connections._conn is None:
            return
        token = uuid.uuid4().hex
        try:
            with self._connections._lock:
                # Read first: the stamp is minted once per file, and a no-op INSERT OR IGNORE
                # still takes the write lock — under a sibling's transaction it blocked for the
                # busy timeout and the except below then dropped the token entirely. First
                # opener still wins via INSERT OR IGNORE; racers converge on the re-read.
                row = self._connections._conn.execute(
                    "SELECT value FROM state_meta WHERE key = ?", (_STATE_DB_GENERATION_KEY,),
                ).fetchone()
                if not (row and row[0]):
                    self._connections._conn.execute(
                        "INSERT OR IGNORE INTO state_meta (key, value) VALUES (?, ?)",
                        (_STATE_DB_GENERATION_KEY, token),
                    )
                    row = self._connections._conn.execute(
                        "SELECT value FROM state_meta WHERE key = ?",
                        (_STATE_DB_GENERATION_KEY,),
                    ).fetchone()
                if row and row[0]:
                    token = str(row[0])
                pragma_row = self._connections._conn.execute("PRAGMA application_id").fetchone()
                current = int(pragma_row[0] or 0) if pragma_row else 0
                if current == 0:
                    current = (int(token[:8], 16) & 0x7FFFFFFF) or 1
                    self._connections._conn.execute(f"PRAGMA application_id={current}")
                self._connections._db_file_application_id = current
                try:
                    self._connections._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.Error:
                    pass
        except sqlite3.Error as exc:
            logger.debug("state.db generation stamp skipped: %s", exc)







    @classmethod
    def _is_structural_corruption_error(cls, exc: BaseException) -> bool:
        """Bare SQLITE_CORRUPT/NOTADB with no FTS provenance: canonical B-tree/schema/freelist damage,
        never repairable from the live write path."""
        return (
            isinstance(exc, sqlite3.DatabaseError)
            and not isinstance(exc, StateDbCorruptError)
            and not cls._is_fts_write_corruption_error(exc)
            and classify_persistence_error(exc) == "corrupt"
        )

    def _corrupt_error(self, prefix: str = "") -> StateDbCorruptError:
        """Build the quarantine error for this handle (message assembled once)."""
        return StateDbCorruptError(f"{prefix}{_STATE_DB_CORRUPT_MSG} (cause: {self._connections._db_corrupt_reason})")

    def _halt_db_corrupt(self, exc: BaseException) -> None:
        """Quarantine this handle and raise; never run in-file repair here."""
        self._connections._db_corrupt = True
        self._connections._db_corrupt_reason = str(exc)
        # Publish the profile-level state first: readiness, /api/status and the session list
        # endpoints read it, and every other handle in this process refuses writes on it.
        mark_storage_corrupt(self.db_path, exc)
        self._connections._disable_close_time_checkpoint()
        logger.error(
            "state.db %s reported structural corruption outside the FTS "
            "indexes (%s); quarantining this handle: no further writes, no "
            "automatic reopen, no explicit WAL checkpoint at close. Stop the "
            "gateway and run `hermes sessions recover --source %s --inspect-only`.", self.db_path, exc,
            self.db_path,
        )
        err = self._corrupt_error()
        for attr in ("sqlite_errorcode", "sqlite_errorname"):
            if getattr(exc, attr, None) is not None:
                setattr(err, attr, getattr(exc, attr))
        raise err from exc




    def _raise_if_db_corrupt(self, *, storage: bool = False) -> None:
        if self._connections._db_corrupt:
            raise self._corrupt_error()
        if storage and storage_state(self.db_path) == STORAGE_CORRUPT:
            # Another handle in this process already saw structural damage on this file.
            # Quarantine this one before it touches SQLite; the error type is the same
            # StateDbCorruptError, so every transcript-diversion owner handles it unchanged.
            self._halt_db_corrupt(sqlite3.DatabaseError(
                "database disk image is malformed (reported earlier in this process: "
                f"{storage_corrupt_reason(self.db_path)})"))

    def _sleep_before_write_retry(self, deadline: float, patience_s: float) -> bool:
        """Sleep one jitter interval if the budget allows; True = retry, False = deadline passed. Small
        jitter for the first _WRITE_RETRY_SLOW_AFTER_S, then slow; never overshoots the deadline."""
        now = time.monotonic()
        if now >= deadline:
            return False
        slow = now - (deadline - patience_s) >= self._WRITE_RETRY_SLOW_AFTER_S
        jitter = random.uniform(*(
            (self._WRITE_RETRY_SLOW_MIN_S, self._WRITE_RETRY_SLOW_MAX_S) if slow
            else (self._WRITE_RETRY_MIN_S, self._WRITE_RETRY_MAX_S)
        ))
        time.sleep(min(jitter, max(deadline - now, 0.001)))
        return True

    def _foreign_state_db_holders(self) -> list[tuple[int, str]]:
        """Foreign processes holding this DB or its WAL sidecars (see hermes_state_holders)."""
        return _foreign_state_db_holders(self.db_path)



    def __enter__(self) -> "SessionDB":
        """``with SessionDB(path) as db:`` closes on exit; owners must release deterministically.

        Ownership of a SessionDB should be released explicitly. Historically an instance with a started
        token writer pinned ITSELF (bound-method writer target plus a strong ``atexit`` drain hook), so
        ``__del__`` never ran for exactly the instances that leaked descriptors (#88033). The writer now
        retires after an idle window and the atexit hook holds only a weak reference, so abandoned handles
        are eventually collectible — but "eventually, after the idle window and a GC cycle" is not a release
        policy. Call sites owning a handle are still expected to close it deterministically (see the
        ownership comments in ``run_agent.py`` and ``tui_gateway/methods_session.py``).
        """
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False  # never suppress the caller's exception

    def close(self):
        """Drain queued token deltas, then a PASSIVE checkpoint on writable handles
        (NOT TRUNCATE: a full WAL reset races the gateway's live writer, tearing
        B-tree pages). A registry-shared instance RELEASES one refcount instead.

        Drains queued token deltas first (the background writer needs the connection). Read-only connections
        never request a checkpoint. See #45383.
        When this instance is shared (opened via ``hermes_state_registry.acquire``), ``close()`` RELEASES one
        refcount instead of tearing down the connection: the registry owns the lifecycle and only closes on
        the final release (#90837). This prevents one caller's close from tearing down the writer connection
        that other callers in the same process are still using — while still letting legacy ``close()`` call
        sites return their reference instead of leaking it.
        """
        if self._shared_registry_owned:
            from hermes_state_registry import release
            release(self)
            return
        self._stop_token_writer()
        hook, self._token_atexit_hook = self._token_atexit_hook, None
        if hook is not None:
            atexit.unregister(hook)
        self._connections.close()

    def __del__(self) -> None:
        """Safety net: close() if the caller forgot. Attribute access stays
        guarded: module teardown order is undefined."""
        if (resource := self.__dict__.get("_connections")) is not None and resource._conn is not None:
            try:
                self.close()
            except Exception:
                pass

    # ── Async token accounting (SessionUsageMixin) ──
    # queue_token_counts() is a deque append; a single-writer thread applies deltas in
    # order, coalescing consecutive deltas whose route fields are EQUAL (so the merged
    # UPDATE equals applying them sequentially). Exact readers call flush_token_counts().
    _TOKEN_DELTA_SUM_FIELDS = (
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
        "api_call_count",
    )
    _TOKEN_DELTA_COST_FIELDS = ("estimated_cost_usd", "actual_cost_usd")
    _TOKEN_DELTA_ROUTE_FIELDS = (
        "model", "cost_status", "cost_source", "pricing_version", "billing_provider", "billing_base_url",
        "billing_mode", "source", "task",
    )

    MAX_TITLE_LENGTH = 100

    # Title provenance, lowest to highest authority: auto-titling may only replace a
    # strictly lower-authority title (``derived`` -> ``llm`` once; never a user-typed name).
    TITLE_SOURCE_DERIVED = _TITLE_SOURCE_DERIVED
    TITLE_SOURCE_LLM = _TITLE_SOURCE_LLM
    TITLE_SOURCE_USER = _TITLE_SOURCE_USER
    _TITLE_SOURCE_RANK = {TITLE_SOURCE_DERIVED: 0, TITLE_SOURCE_LLM: 1, TITLE_SOURCE_USER: 2}

    # Bot Mode's canonical chat is resolved by exact-title lookup: the title IS the identity,
    # so _set_session_title refuses renames of a hidden row holding it.
    # Bot Mode's forever-chat registry: the session titled exactly this, on a bot's profile, IS the bot's
    # canonical chat — resolved by exact-title lookup on every open (no session-id pointer exists). See
    # #92473.
    CANONICAL_BOT_CHAT_TITLE = "Bot Chat"

    # ── Message storage constants (SessionMessagesMixin) ──
    # Prefix marking JSON-encoded structured content; NUL cannot collide with text.
    _CONTENT_JSON_PREFIX = "\x00json:"
    #: Reactions live inside ``display_metadata`` so they survive row rewrites.
    REACTIONS_METADATA_KEY = "reactions"
    # Columns every conversation projection decodes; ``active`` rides along so a display read
    # can split compaction-archived rows without a second query. Contract: must include every
    # ``agent.transcript_repair._OWNED_COLUMNS`` column, because replay stamps
    # ``transcript_row_snapshot(row)`` from these rows (token_count is hashed there, not decoded).
    _CONVERSATION_ROW_COLUMNS = (
        "id, role, content, tool_call_id, tool_calls, tool_name, effect_disposition, "
        "finish_reason, reasoning, reasoning_content, reasoning_details, "
        "codex_reasoning_items, codex_message_items, platform_message_id, observed, "
        "_compressed_summary, timestamp, token_count, active, api_content, display_kind, display_metadata, message_uid, "
        "absorbed_message_uids, tool_call_uids, tool_call_uid"
    )

    # ── Meta key/value (scheduler bookkeeping) ──

    def get_meta(self, key: str) -> Optional[str]:
        """Read state_meta[key] on self._connections._lock (not _read_ctx): fts_rebuild_step reads progress before its
        write transaction and a WAL reader would not see it."""
        with self._connections._lock:
            row = self._connections._conn.execute("SELECT value FROM state_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def set_meta(self, key: str, value: str, *, cursor: Optional[sqlite3.Cursor] = None) -> None:
        """Upsert state_meta[key]; with ``cursor`` the write is inline (the caller already holds a
        transaction — nesting BEGIN IMMEDIATE would deadlock)."""
        sql = (
            "INSERT INTO state_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        if cursor is not None:
            cursor.execute(sql, (key, value))
        else:
            self._write_sql(sql, (key, value))

    def retag_kanban_worker_sessions(self, workspaces_root: str) -> int:
        """Retag legacy kanban worker rows from ``cli`` to ``kanban`` by cwd under the board's workspaces
        root; gated once per root via state_meta. Returns rows retagged."""
        prefix = str(workspaces_root).rstrip("/\\")
        if not prefix:
            return 0
        gate = f"kanban_worker_source_retagged:{prefix}"
        if self.get_meta(gate) == "1":
            return 0
        def _do(conn):
            esc = _escape_like(prefix)
            cursor = conn.execute(
                "UPDATE sessions SET source = 'kanban' "
                "WHERE source = 'cli' AND (cwd = ? OR cwd LIKE ? ESCAPE '\\' "
                "OR cwd LIKE ? ESCAPE '\\')",
                (prefix, f"{esc}/%", f"{esc}\\\\%"),
            )
            # rowcount BEFORE set_meta reuses this cursor for its INSERT.
            retagged = cursor.rowcount or 0
            self.set_meta(gate, "1", cursor=cursor)
            return retagged
        return self._execute_write(_do)

    def is_kanban_owned_session(self, session_id: str) -> bool:
        """True when this session — or any segment of the compression lineage a resume would
        materialize — belongs to the Kanban dispatcher (``source``/``created_source`` =
        ``'kanban'``): the transcript of a worker run, not a human conversation (#68779).

        Both columns are checked: ``source`` is live routing state the dispatcher tags
        (``HERMES_SESSION_SOURCE=kanban``) and the legacy retag rewrites, while immutable
        ``created_source`` survives later surface flips. The lineage is the VERIFIED
        compression chain (``_resume_lineage_ids``) — exactly the rows a resume loads — so a
        worker transcript stays kanban-owned across rotations, while a delegate/branch child
        of a worker (a DIFFERENT conversation) is not swept in. Plain classification, not a
        gate: the resume-time guard (``hermes_cli/kanban_resume_guard.py``) owns the decision
        and the dispatcher-owned exemption."""
        lineage = self._resume_lineage_ids(session_id)
        if not lineage:
            return False
        rows = self._read_all(
            f"SELECT 1 FROM sessions WHERE id IN ({_placeholders(lineage)}) "
            "AND (source = 'kanban' OR created_source = 'kanban') LIMIT 1",
            tuple(lineage))
        return bool(rows)

    def list_meta_prefix(self, prefix: str) -> list[tuple[str, str]]:
        """``[(key, value), ...]`` for state_meta keys starting with the literal
        ``prefix`` (LIKE wildcards escaped) — e.g. ``loop:<session_id>`` rows."""
        if not prefix:
            return []
        rows = self._read_all(
            "SELECT key, value FROM state_meta WHERE key LIKE ? ESCAPE '\\'", (_escape_like(prefix) + "%",),
        )
        return [(row[0], row[1]) for row in rows]


class AsyncSessionDB:
    """Async door onto SessionDB: every call runs via asyncio.to_thread so a blocking SQLite call
    never freezes the event loop (no method returns a live cursor)."""

    def __init__(self, db: SessionDB) -> None:
        self._db = db

    def __getattr__(self, name: str):
        attr = getattr(self._db, name)
        if not callable(attr):
            return attr
        async def _offloaded(*args, **kwargs):
            return await asyncio.to_thread(attr, *args, **kwargs)
        return _offloaded
