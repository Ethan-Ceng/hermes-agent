"""Durable delivery-obligation ledger for gateway final responses (rows in the shared ``state.db``;
WAL, owner pid + process-start liveness, bounded retention) so a crash between finalize and
platform ACK cannot lose a response silently. Checkpoints: record_obligation() 'pending' before
any send | mark_attempting() 'attempting' right before the await | mark_delivered() 'delivered'
only on SendResult.success | mark_failed() 'failed' on a definitive rejection. Crash semantics
(never silently resend an ambiguous send): pending = never started, redeliver plainly; attempting
= crashed mid-await, platform MAY have it, redeliver WITH a visible recovered marker; failed =
rejected once, restart is a retry boundary, also marked; delivered = prune. Attempts are capped
and stale rows expire, both -> 'abandoned' (kept briefly, then pruned). Everything is
best-effort: ledger failures must never block a send; callers wrap every call in try/except.
"""

from __future__ import annotations
from gateway.delivery_rules import MAX_ATTEMPTS, STALE_AFTER_SECONDS, _RETENTION_SECONDS, _MAX_ROWS, RECOVERED_MARKER, RECONNECTED_MARKER, FLOOD_MARKER, _RUNTIME_RETRYABLE_ERRORS, _RETRY_BACKOFF_SECONDS, FLOOD_ERROR_PREFIX, FLOOD_RETRY_DEFAULT_SECONDS, FLOOD_RETRY_CAP_SECONDS, FLOOD_RETRY_SLACK_SECONDS, _RAW_FLOOD_RE, _raw_flood_wait, is_reconnect_only, is_flood_error, flood_wait_seconds, flood_retry_delay, _failed_stamp, flood_not_before, retry_not_before, _claimed_row

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from hermes_cli.sqlite_util import add_column_if_missing
from hermes_constants import get_process_hermes_home

logger = logging.getLogger(__name__)
_DB_LOCK = threading.Lock()

def _db_path():
    # Launch home, not get_hermes_home(): a multiplexed gateway records a served profile's replies
    # under that profile's home override, but the boot sweep reads from the launch context, so both
    # must open the one shared store (adapter_profile tells the bots apart). No get_hermes_home()
    # fallback for an unset HERMES_HOME: a default gateway run in the foreground has none.
    return get_process_hermes_home() / "state.db"


def _connect() -> sqlite3.Connection:
    from hermes_cli.sqlite_util import open_db

    # Shared state.db: SessionDB owns the durable PRAGMA set; this opener keeps the plain-tuple rows
    # and the 10 s busy timeout it always had.
    return open_db(_db_path(), db_label="state.db (delivery_ledger)", busy_timeout_ms=10_000,
                   row_factory=None, initialize=_initialize_schema)


def _initialize_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS delivery_obligations (
            obligation_id TEXT PRIMARY KEY,
            session_key TEXT NOT NULL,
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            thread_id TEXT,
            content TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            owner_pid INTEGER,
            owner_started_at INTEGER,
            last_error TEXT,
            adapter_profile TEXT
        )"""
    )
    if "adapter_profile" not in {row[1] for row in conn.execute("PRAGMA table_info(delivery_obligations)")}:
        add_column_if_missing(conn, "delivery_obligations", "adapter_profile", "adapter_profile TEXT")


def _transaction():
    from hermes_cli.sqlite_util import transaction

    return transaction(_connect())


def _start_time(pid: int) -> Optional[int]:
    try:
        from gateway.status import get_process_start_time  # lazy: tests monkeypatch gateway.status
        return get_process_start_time(pid)
    except Exception:
        return None


def _owner_stamp() -> tuple[int, Optional[int]]:
    pid = os.getpid()
    return pid, _start_time(pid)


def _owner_alive(pid: Any, started_at: Any) -> bool:
    """True when the recorded owning process still exists (pid + start time)."""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    current_start = _start_time(pid)
    if current_start is None:
        # Start time unreadable: alive iff the pid exists. Route through the cross-platform probe — on Windows
        # ``os.kill(pid, 0)`` is NOT a no-op (bpo-14484: it maps to ``GenerateConsoleCtrlEvent(0, pid)`` and could
        # Ctrl+C the gateway's own console group). ``_pid_exists`` keeps EPERM-means-alive (pid owned by another user).
        try:
            from gateway.status import _pid_exists
        except Exception:
            if os.name == "nt":
                return False  # never fall back to a raw sig-0 probe on Windows
            try:
                os.kill(pid, 0)  # windows-footgun: ok — POSIX-only fallback branch
                return True
            except OSError as exc:  # incl. ProcessLookupError; EPERM means the pid exists
                return isinstance(exc, PermissionError)
        try:
            return bool(_pid_exists(pid))
        except Exception:
            return False
    try:
        from gateway.status import start_time_fingerprints_match
        return started_at is None or start_time_fingerprints_match(started_at, current_start)
    except (TypeError, ValueError):
        return True


def compute_obligation_id(session_key: str, message_ref: str, content: str) -> str:
    """Stable id: same turn + same content re-records idempotently, while distinct threads/topics on one
    chat never collide (session_key carries platform/chat/thread; ``message_ref`` = inbound message id)."""
    return hashlib.sha256(f"{session_key}|{message_ref}|{content}".encode("utf-8", "replace")).hexdigest()[:24]


def record_obligation(*, obligation_id: str, session_key: str, platform: str, chat_id: str,
                      thread_id: Optional[str], content: str, adapter_profile: Optional[str] = None):
    """Record a final response as owed to the platform (state='pending')."""
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger.record_obligation(obligation_id=obligation_id, session_key=session_key, platform=platform,
            chat_id=chat_id, thread_id=thread_id, content=content, adapter_profile=adapter_profile)
    now, (pid, started) = time.time(), _owner_stamp()
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO delivery_obligations
               (obligation_id, session_key, platform, chat_id, thread_id,
                content, state, attempts, created_at, updated_at,
                owner_pid, owner_started_at, adapter_profile)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?)""",
            (obligation_id, session_key, platform, str(chat_id), str(thread_id) if thread_id else None,
             content, now, now, pid, started, str(adapter_profile).strip() if adapter_profile else "default"))
        # Same transaction, same connection: the cron ledgers prune this way too
        # (cron/delivery_queue._prune_terminal_unlocked, cron/executions._prune_unlocked).
        _prune_unlocked(conn, now)


def record_crash_left_reply(*, obligation_id: str, session_key: str, platform: str, chat_id: str,
                            thread_id: Optional[str], content: str, since: float,
                            adapter_profile: Optional[str] = None) -> None:
    """Adopt a reply a killed process persisted but never ledgered. Unowned, so this boot's sweep
    claims it, and 'attempting', because a streamed reply may already be on screen: it is
    redelivered once, with the recovered marker. A no-op when the same reply was already ledgered
    since *since* (the turn start), and idempotent across boots that die before their sweep."""
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger.record_crash_left_reply(obligation_id=obligation_id, session_key=session_key, platform=platform,
            chat_id=chat_id, thread_id=thread_id, content=content, since=since, adapter_profile=adapter_profile)
    now = time.time()
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO delivery_obligations
               (obligation_id, session_key, platform, chat_id, thread_id,
                content, state, attempts, created_at, updated_at,
                owner_pid, owner_started_at, adapter_profile)
               SELECT ?, ?, ?, ?, ?, ?, 'attempting', 0, ?, ?, NULL, NULL, ?
               WHERE NOT EXISTS (SELECT 1 FROM delivery_obligations
                                 WHERE session_key = ? AND content = ? AND created_at >= ?)""",
            (obligation_id, session_key, platform, str(chat_id), str(thread_id) if thread_id else None,
             content, now, now, str(adapter_profile).strip() if adapter_profile else "default",
             session_key, content, since))


def mark_attempting(obligation_id: str) -> None:
    _update_state(obligation_id, "attempting")


def mark_delivered(obligation_id: str) -> None:
    _update_state(obligation_id, "delivered")


def mark_failed(obligation_id: str, error: str = "") -> None:
    _update_state(obligation_id, "failed", error=error)


def release_runtime_claim(obligation_id: str, error: str = "") -> bool:
    """Return an unsent runtime claim to ``failed`` without spending an attempt.

    Runtime recovery claims before clearing ``resume_pending`` so two reconnect paths cannot send the
    same row; if the flag cannot be cleared no send was attempted and the claim must not consume the
    redelivery budget. Fail-closed to the exact current process instance and ``attempting`` state."""
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger.release_runtime_claim(obligation_id, error)
    pid, started = _owner_stamp()
    if started is None:
        return False
    with _DB_LOCK, _transaction() as conn:
        cursor = conn.execute(
            """UPDATE delivery_obligations
               SET state='failed', attempts=CASE
                       WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                   updated_at=?, last_error=?
               WHERE obligation_id=? AND state='attempting'
                 AND owner_pid IS ? AND owner_started_at IS ?""",
            (time.time(), error[:500] if error else None, obligation_id, pid, started))
    return bool(cursor.rowcount)


def _update_state(obligation_id: str, state: str, error: str = "") -> None:
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger._mark(obligation_id, state, error)
    with _DB_LOCK, _transaction() as conn:
        conn.execute(
            """UPDATE delivery_obligations
               SET state=?, updated_at=?, last_error=?
               WHERE obligation_id=?""",
            (state, time.time(), error[:500] if error else None, obligation_id))




def sweep_recoverable(now: Optional[float] = None, *, deliverable_platforms: Optional[set] = None,
                      deliverable_targets: Optional[set] = None) -> list[dict[str, Any]]:
    """Claim undelivered rows owned by dead processes; return them for redelivery.

    Claiming atomically re-stamps the owner to THIS process, moves the row to 'attempting' and increments
    ``attempts`` (the UPDATE is guarded on the previous owner stamp, so a second gateway racing the same
    sweep cannot double-claim).
    Rows over the attempts cap or stale cutoff become 'abandoned'. ``deliverable_platforms`` restricts
    claiming to platforms the caller can send on this boot: ``attempts`` is the redelivery budget and
    must only be spent on a real send, else a platform that failed to connect burns one attempt per boot
    and hits the cap having never been sent once (the stale cutoff still bounds untouched rows).
    ``deliverable_targets`` further scopes multiplexed gateways by exact ``(platform, adapter_profile)``
    so one connected bot cannot spend another disconnected bot's retry budget.

    A flood-refused row still inside its wait is adopted (owner re-stamped, no attempt spent) and
    returned flagged ``adopted`` with its ``not_before``: the caller clears its session's resume flag
    like any other claimed row, since the answer is in the ledger, but must not send it; the flood
    timer does once the wait has passed. A legacy row without ``adapter_profile`` is normalised to
    ``'default'`` on claim or adoption (the caller only accepts such rows when it is not multiplexed),
    because the runtime sweep matches profiles exactly and could otherwise never claim it."""
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger.sweep_recoverable(now, deliverable_platforms=deliverable_platforms, deliverable_targets=deliverable_targets)
    now, (pid, started) = now if now is not None else time.time(), _owner_stamp()
    claimed: list[dict[str, Any]] = []
    with _DB_LOCK, _transaction() as conn:
        rows = conn.execute(
            """SELECT obligation_id, session_key, platform, chat_id, thread_id,
                      content, state, attempts, created_at,
                      owner_pid, owner_started_at, adapter_profile, last_error, updated_at
               FROM delivery_obligations
               WHERE state IN ('pending', 'attempting', 'failed')"""
        ).fetchall()
        for (oid, session_key, platform, chat_id, thread_id, content, state, attempts, created_at,
             owner_pid, owner_started_at, adapter_profile, last_error, updated_at) in rows:
            if _owner_alive(owner_pid, owner_started_at):
                continue  # a live gateway still owns this row
            if attempts >= MAX_ATTEMPTS or (now - created_at) > STALE_AFTER_SECONDS:  # exhausted -> abandoned
                conn.execute(
                    """UPDATE delivery_obligations
                       SET state='abandoned', updated_at=? WHERE obligation_id=?""", (now, oid))
                continue
            if ((deliverable_platforms is not None and platform not in deliverable_platforms)
                    or (deliverable_targets is not None and (platform, adapter_profile) not in deliverable_targets)):
                continue  # no adapter this boot — claiming would spend an attempt on a no-op
            flood_row = state == "failed" and is_flood_error(last_error)
            if flood_row and now < flood_not_before(updated_at, last_error):
                # Still inside the platform's wait: adopt the dead owner's row without spending an attempt
                # (state and error kept) so this process's flood timer can claim it once the wait passes.
                cursor = conn.execute(
                    """UPDATE delivery_obligations
                       SET owner_pid=?, owner_started_at=?,
                           adapter_profile=COALESCE(adapter_profile, 'default')
                       WHERE obligation_id=? AND (owner_pid IS ? OR owner_pid=?)""",
                    (pid, started, oid, owner_pid, owner_pid))
                if cursor.rowcount:
                    claimed.append({
                        "obligation_id": oid, "session_key": session_key, "platform": platform,
                        "chat_id": chat_id, "thread_id": thread_id, "content": content,
                        "profile": adapter_profile or "default", "attempts": attempts,
                        "adopted": True, "not_before": flood_not_before(updated_at, last_error)})
                continue
            # Every claim starts a send, so the row leaves 'pending'/'failed' for 'attempting' in the same
            # CAS: a boot killed inside the redelivery then leaves proof the platform may have it (next boot
            # marks it), and the runtime sweep, which only takes 'failed', cannot re-claim it mid-send. A
            # claimed flood row also drops its stale refusal, so an interrupted resend has no error.
            cursor = conn.execute(
                """UPDATE delivery_obligations
                   SET owner_pid=?, owner_started_at=?, attempts=attempts+1, updated_at=?,
                       adapter_profile=COALESCE(adapter_profile, 'default'), state='attempting',
                       last_error=CASE WHEN ? THEN NULL ELSE last_error END
                   WHERE obligation_id=? AND (owner_pid IS ? OR owner_pid=?)""",
                (pid, started, now, 1 if flood_row else 0, oid, owner_pid, owner_pid))
            if cursor.rowcount:
                # A never-claimed pending row was never sent: redeliver plainly. Anything else (crashed
                # mid-await, other rejection, a flood refusal whose earlier chunks the platform may have
                # accepted, or a pending row an older build already claimed and may have sent) carries
                # the marker.
                claimed.append(_claimed_row(oid, session_key, platform, chat_id, thread_id, content, attempts,
                                            adapter_profile or "default",
                                            needs_marker=state != "pending" or attempts > 0, flood=flood_row))
    return claimed


def sweep_failed_for_runtime(platform: str, now: Optional[float] = None, *,
                             profile: Optional[str] = None) -> list[dict[str, Any]]:
    """Claim this process's failed rows that are due for another send, for one adapter.

    ``profile`` scopes multiplexed gateways to the bot identity that owned the failed send (``None`` =
    primary/default adapter); unowned rows and rows owned by another process are left for the
    startup/dead-owner sweep. Startup recovery ignores rows owned by a live gateway, so a response
    rejected with ``send_path_degraded`` would stay stranded when only the adapter reconnects; this closes
    that gap without weakening ownership: only rows stamped to this exact process instance, only rows
    past their ``retry_not_before`` deadline, same attempts/staleness bounds, every update guarded by the
    prior owner stamp and ``failed`` state. Claimed rows always carry a marker (the failed send's ack is not safe to
    infer): the reconnect one, or the rate-limit one for a flood-refused row."""
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger.sweep_failed_for_runtime(platform, now, profile=profile)
    now, (pid, started) = now if now is not None else time.time(), _owner_stamp()
    if started is None:  # PID alone cannot distinguish this process from a stale row left after PID
        return []        # reuse; runtime replay is optional, so fail closed (startup recovery remains).
    expected_profile = "default" if not profile or profile == "default" else str(profile)
    claimed: list[dict[str, Any]] = []
    with _DB_LOCK, _transaction() as conn:
        rows = conn.execute(
            """SELECT obligation_id, session_key, platform, chat_id, thread_id,
                      content, attempts, created_at, owner_pid,
                      owner_started_at, last_error, adapter_profile, updated_at
               FROM delivery_obligations
               WHERE state='failed' AND platform=?""", (platform,)).fetchall()
        for (oid, session_key, row_platform, chat_id, thread_id, content, attempts, created_at,
             owner_pid, owner_started_at, last_error, adapter_profile, updated_at) in rows:
            # Exact process-start matching prevents PID reuse from stealing work.
            if adapter_profile != expected_profile or owner_pid != pid or owner_started_at != started:
                continue
            due = retry_not_before(updated_at, last_error, attempts)
            if due is None:
                continue
            owner_guard = (now, oid, owner_pid, owner_started_at)
            if attempts >= MAX_ATTEMPTS or (now - created_at) > STALE_AFTER_SECONDS:  # exhausted -> abandoned
                conn.execute(
                    """UPDATE delivery_obligations
                       SET state='abandoned', updated_at=?
                       WHERE obligation_id=? AND state='failed'
                         AND owner_pid IS ? AND owner_started_at IS ?""", owner_guard)
                continue
            if now < due:
                continue  # the platform's wait or the backoff has not passed; the timer comes back for it
            # The claim clears the stale error: this is a fresh attempt, and if it is interrupted the next
            # boot must see 'attempting' with no proof of non-delivery, hence the marker.
            cursor = conn.execute(
                """UPDATE delivery_obligations
                   SET state='attempting', attempts=attempts+1, updated_at=?, last_error=NULL
                   WHERE obligation_id=? AND state='failed'
                     AND owner_pid IS ? AND owner_started_at IS ?""", owner_guard)
            if cursor.rowcount:
                # The failed send's ack may have been lost (reconnect) or its earlier chunks accepted
                # (flood): every runtime redelivery carries a marker. The pre-claim error rides along so a
                # claim released unsent keeps its flood retry eligibility.
                claimed.append(_claimed_row(oid, session_key, row_platform, chat_id, thread_id, content,
                                            attempts, adapter_profile, needs_marker=True, runtime=True,
                                            flood=is_flood_error(last_error), last_error=last_error))
    return claimed


def pending_retries(now: Optional[float] = None) -> list[dict[str, Any]]:
    """This process's failed rows that still await redelivery, one entry per adapter identity with the
    earliest deadline (``not_before``). The runner arms one redelivery timer per entry, so a row adopted
    at boot, skipped because its wait had not passed, or rejected again is never stranded. Rows past the
    attempts cap or stale cutoff are left for the sweeps to abandon."""
    from gateway.delivery_backend import postgres_ledger
    if (ledger := postgres_ledger()) is not None:
        return ledger.pending_retries(now)
    now, (pid, started) = now if now is not None else time.time(), _owner_stamp()
    if started is None:
        return []
    with _DB_LOCK, _transaction() as conn:
        rows = conn.execute(
            """SELECT platform, adapter_profile, updated_at, last_error, attempts, created_at
               FROM delivery_obligations
               WHERE state='failed' AND owner_pid IS ? AND owner_started_at IS ?""", (pid, started)).fetchall()
    earliest: dict[tuple, float] = {}
    for platform, adapter_profile, updated_at, last_error, attempts, created_at in rows:
        # Reconnect-only rows (a claim released because the adapter was gone) are re-claimed by the
        # reconnect sweep; a timer would claim and release them every tick until the adapter is back.
        if is_reconnect_only(last_error):
            continue
        due = retry_not_before(updated_at, last_error, attempts)
        if due is None or attempts >= MAX_ATTEMPTS or (now - created_at) > STALE_AFTER_SECONDS:
            continue
        key = (platform, adapter_profile or "default")
        if key not in earliest or due < earliest[key]:
            earliest[key] = due
    return [{"platform": platform, "profile": profile, "not_before": due}
            for (platform, profile), due in sorted(earliest.items())]


def _prune_unlocked(conn, now: float) -> None:
    """Retention DELETEs on the caller's open connection — must run inside the caller's transaction."""
    conn.execute(
        """DELETE FROM delivery_obligations
           WHERE state IN ('delivered', 'abandoned') AND updated_at < ?""", (now - _RETENTION_SECONDS,))
    total = conn.execute("SELECT COUNT(*) FROM delivery_obligations").fetchone()[0]
    if total > _MAX_ROWS:
        conn.execute(
            """DELETE FROM delivery_obligations WHERE obligation_id IN (
                 SELECT obligation_id FROM delivery_obligations
                 ORDER BY CASE state
                            WHEN 'delivered' THEN 0
                            WHEN 'abandoned' THEN 1
                            ELSE 2
                          END, updated_at ASC
                 LIMIT ?)""", (total - _MAX_ROWS,))


def ledger_enabled(config: Optional[dict[str, Any]] = None) -> bool:
    """Read the ``gateway.delivery_ledger`` config gate (default on)."""
    try:
        if config is None:
            from hermes_cli.config import load_config
            config = load_config()
        value = (config.get("gateway") or {}).get("delivery_ledger", True)
        return value.strip().lower() not in {"false", "0", "no", "off"} if isinstance(value, str) else bool(value)
    except Exception:
        return True
