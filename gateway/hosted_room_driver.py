"""Durable execution state for a same-gateway hosted room driver.

Owns only the driver lease and task state machine: no model calls, no sessions, no dependency on the
hosted-room event log. Callers supply the database path and clock so recovery and fencing are testable
without process-global state.
"""

from __future__ import annotations
from hermes_db.domains.rooms.driver_rules import Clock, DriverLease, DriverStateError, DriverValidationError, InvalidTaskTransitionError, LeaseHeldError, MAX_IDENTIFIER_CHARS, MAX_PROMPT_BYTES, MAX_RESULT_JSON_BYTES, MAX_RETAINED_TERMINAL_TASKS, MAX_TASK_PRUNE_BATCH, RoomUnavailableError, StaleLeaseError, StaleTaskError, TASK_STATUSES, TERMINAL_STATUSES, TERMINAL_TASK_RETENTION_SECONDS, TaskAttempt, TaskConflictError, TaskIdentity, TaskStatus, _TASK_COLUMN_ORDER, _bounded_int, _cancel_generation, _cancel_replay, _canonical_json, _check_same_room, _expected_generations, _generations_match, _identifier, _lease_from_row, _lease_row_matches, _lease_window, _require_cancel_generation, _run_fence, _settlement, _task_from_row, _task_identity_from_row, _task_payload, _terminal_settlement_id, _timestamp, validate_bound_task_manifest

import dataclasses
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Literal, get_args
from gateway.hosted_room_storage import room_operation, assert_sqlite_location

from gateway.hosted_rooms_common import DbPath, fenced_update, table_columns, transaction
from hermes_db.domains.rooms.rules import bounded_int, canonical_json, compact_json, identifier, text

TerminalStatus = Literal["settled", "failed"]

# The live rows shown individually; remaining task states are counted.
from hermes_db.domains.rooms.driver_rules import SHOWN_TASK_STATUSES, RoomChangeRows

_LEASE_COLUMNS = frozenset({
    "room_id", "gateway_id", "authority_epoch", "process_generation", "lease_generation", "expires_at", "acquired_at",
    "updated_at", "released_at"})
_TASK_COLUMNS = frozenset(_TASK_COLUMN_ORDER)
_TASK_ORDER = "ORDER BY source_event_seq, created_at, task_id"
_SELECT_LEASE = "SELECT * FROM hosted_room_driver_leases WHERE room_id=?"
_SELECT_TASK = "SELECT * FROM hosted_room_driver_tasks WHERE room_id=? AND task_id=?"
_TASK_INDEX_SQL = """CREATE INDEX {if_not_exists}idx_hosted_room_driver_tasks_status
           ON hosted_room_driver_tasks(room_id, status, source_event_seq, created_at, task_id)"""

# --- Fenced task UPDATE statements (one per state-machine transition) ---------
# Every transition is "UPDATE ... SET <set> WHERE room_id=? AND task_id=? AND <fence>"; the fence names the
# expected status plus the generations that must not have moved.
_GENERATION_FENCE = "execution_generation=? AND cancel_generation=?"
_RUN_FENCE = "run_gateway_id=? AND run_process_generation=? AND run_lease_generation=?"
_SETTLE_SET = "status=?, settlement_id=?, settlement_status=?, result_json=?, terminal_at=?, updated_at=?"
_REQUEUE_SET = "status='queued', run_gateway_id=NULL, run_process_generation=NULL, run_lease_generation=NULL"
_CANCEL_SET = "status='cancelled', cancel_generation=?, cancel_id=?, terminal_at=?, updated_at=?"


def _task_update(set_clause: str, fence: str) -> str:
    return f"UPDATE hosted_room_driver_tasks SET {set_clause} WHERE room_id=? AND task_id=? AND {fence}"


def _generation_update(set_clause: str, status: str) -> str:
    """Transition fenced on ``status`` + both generations (terminal settlements and the recovery family)."""
    return _task_update(set_clause, f"status='{status}' AND {_GENERATION_FENCE}")


_SETTLE_RUNNING_SQL = _generation_update(_SETTLE_SET, "running") + f" AND {_RUN_FENCE}"
_SETTLE_STOPPING_SQL = _generation_update(_SETTLE_SET, "stopping")
_REQUEUE_RUNNING_SQL = _task_update(
    f"{_REQUEUE_SET}, started_at=NULL, updated_at=?", f"status='running' AND {_GENERATION_FENCE} AND {_RUN_FENCE}")
_CANCEL_QUEUED_SQL = _task_update(_CANCEL_SET, "status IN ('queued', 'deferred') AND cancel_generation=?")
_BEGIN_STOP_SQL = _task_update(
    "status='stopping', cancel_generation=?, cancel_id=?, updated_at=?",
    "status IN ('running', 'indeterminate') AND cancel_generation=?")
_COMPLETE_STOP_SQL = _task_update(
    "status='cancelled', terminal_at=?, updated_at=?", "status='stopping' AND cancel_id=? AND cancel_generation=?")

# Lease-first recovery transitions: name -> (fenced status, SET clause, generation-guard stale message,
# row stale message); the UPDATE is _generation_update(set_clause, status).
_INDETERMINATE_STALE = "indeterminate task generation changed"
_GENERATION_TRANSITIONS = {
    "resolve": ("indeterminate", _SETTLE_SET, _INDETERMINATE_STALE, "indeterminate task changed during reconciliation"),
    "resolve_cancel": (
        "indeterminate", _CANCEL_SET, "indeterminate cancellation proof is stale",
        "indeterminate cancellation proof lost its fence"),
    "requeue": (
        "indeterminate", f"{_REQUEUE_SET}, started_at=NULL, indeterminate_at=NULL, updated_at=?", _INDETERMINATE_STALE,
        "indeterminate task changed during requeue"),
    "defer": (
        "indeterminate", "status='deferred', result_json=?, terminal_at=?, updated_at=?", _INDETERMINATE_STALE,
        "indeterminate task changed during deferral"),
    "defer_stopping": (
        "stopping", "status='deferred', result_json=?, terminal_at=?, updated_at=?",
        "stopping task generation changed", "stopping task changed during deferral"),
    "reopen_deferred": (
        "deferred",
        "status='indeterminate', result_json=NULL, terminal_at=NULL, started_at=?, indeterminate_at=?, updated_at=?",
        "deferred task generation changed", "deferred task changed during reopen"),
    "requeue_deferred": (
        "deferred",
        f"{_REQUEUE_SET}, result_json=NULL, started_at=NULL, terminal_at=NULL, indeterminate_at=NULL, updated_at=?",
        "deferred task generation changed", "deferred task changed during requeue")}






















def _create_task_table(conn: sqlite3.Connection, table: str = "hosted_room_driver_tasks") -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {table} (
            room_id TEXT NOT NULL, task_id TEXT NOT NULL, thread_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            source_event_seq INTEGER NOT NULL CHECK (source_event_seq >= 1),
            payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'running', 'settled', 'failed', 'cancelled', 'indeterminate', 'deferred', 'stopping')),
            execution_generation INTEGER NOT NULL DEFAULT 0 CHECK (execution_generation >= 0),
            cancel_generation INTEGER NOT NULL DEFAULT 0 CHECK (cancel_generation >= 0),
            run_gateway_id TEXT, run_process_generation TEXT, run_lease_generation INTEGER, cancel_id TEXT,
            settlement_id TEXT, settlement_status TEXT, result_json TEXT, created_at REAL NOT NULL,
            updated_at REAL NOT NULL, started_at REAL, terminal_at REAL, indeterminate_at REAL,
            PRIMARY KEY (room_id, task_id), UNIQUE (room_id, thread_id, turn_id),
            FOREIGN KEY (room_id) REFERENCES hosted_rooms(room_id))""")


def _initialize_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS hosted_room_driver_leases (
            room_id TEXT PRIMARY KEY, gateway_id TEXT NOT NULL,
            authority_epoch INTEGER NOT NULL CHECK (authority_epoch >= 1), process_generation TEXT NOT NULL,
            lease_generation INTEGER NOT NULL CHECK (lease_generation >= 1),
            expires_at REAL NOT NULL, acquired_at REAL NOT NULL, updated_at REAL NOT NULL, released_at REAL,
            FOREIGN KEY (room_id) REFERENCES hosted_rooms(room_id))""")
    _create_task_table(conn)
    _validate_schema(conn)
    conn.execute(_TASK_INDEX_SQL.format(if_not_exists="IF NOT EXISTS "))


def _validate_schema(conn: sqlite3.Connection) -> None:
    columns = table_columns(conn, "hosted_room_driver_leases"), table_columns(conn, "hosted_room_driver_tasks")
    if columns != (_LEASE_COLUMNS, _TASK_COLUMNS):
        raise DriverStateError(
            "unsupported unpublished hosted-room driver schema; "
            "recreate the driver tables before starting the driver")
    for table in ("hosted_room_driver_leases", "hosted_room_driver_tasks"):
        if not any(
            row[2] == "hosted_rooms" and row[3] == "room_id" and row[4] == "room_id"
            for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()):
            raise DriverStateError(f"{table} is missing its hosted_rooms foreign key")


def _schema_objects_exist(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("""SELECT name FROM sqlite_master WHERE type='table'
           AND name IN ('hosted_room_driver_leases', 'hosted_room_driver_tasks')""").fetchall()
    if {row[0] for row in rows} != {"hosted_room_driver_leases", "hosted_room_driver_tasks"}:
        return False
    index = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_hosted_room_driver_tasks_status'").fetchone()
    return index is not None


def _migrate_task_status_constraint(conn: sqlite3.Connection) -> None:
    """Expand the unpublished task-state CHECK without losing durable work."""
    conn.execute("DROP INDEX IF EXISTS idx_hosted_room_driver_tasks_status")
    _create_task_table(conn, "hosted_room_driver_tasks_next")
    columns = ", ".join(_TASK_COLUMN_ORDER)
    conn.execute(
        f"INSERT INTO hosted_room_driver_tasks_next ({columns}) SELECT {columns} FROM hosted_room_driver_tasks")
    conn.execute("DROP TABLE hosted_room_driver_tasks")
    conn.execute("ALTER TABLE hosted_room_driver_tasks_next RENAME TO hosted_room_driver_tasks")
    conn.execute(_TASK_INDEX_SQL.format(if_not_exists=""))


def _schema_ready(conn: sqlite3.Connection) -> bool:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {"hosted_room_driver_leases", "hosted_room_driver_tasks"} <= tables:
        _validate_schema(conn)
    if not _schema_objects_exist(conn):
        return False
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='hosted_room_driver_tasks'").fetchone()
    sql = str(row[0] or "").lower() if row else ""
    return "'stopping'" in sql and "'deferred'" in sql


def initialize(conn: sqlite3.Connection) -> None:
    """Run the existing task constraint migration under the caller's explicit initialization transaction."""
    if _schema_objects_exist(conn):
        if not _schema_ready(conn):
            _migrate_task_status_constraint(conn)
        _validate_schema(conn)
    else:
        _initialize_schema(conn)


def _connect(db_path: DbPath) -> sqlite3.Connection:
    from hermes_cli.db_sqlite_policy import open_ready_profile_sqlite

    assert_sqlite_location(db_path)
    conn = open_ready_profile_sqlite(
        db_path, db_label="state.db (hosted_room_driver)", ready=_schema_ready,
        busy_timeout_ms=10_000, foreign_keys=True,
    )
    try:
        _validate_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _transaction(db_path: DbPath):
    return transaction(_connect, db_path, immediate=True)








# Task-view casts per row column (columns after payload_digest in _TASK_COLUMN_ORDER, same key order;
# result_json is exposed as "result"). Columns not listed are passed through untouched.




def _load_task(conn: sqlite3.Connection, identity: TaskIdentity, *, required: bool = True) -> sqlite3.Row | None:
    row = conn.execute(_SELECT_TASK, (identity.room_id, identity.task_id)).fetchone()
    if row is None:
        if required:
            raise TaskConflictError("task does not exist")
        return None
    if _task_identity_from_row(row) != identity:
        raise TaskConflictError("task_id is already bound to a different turn")
    return row


def _tasks_in_order(conn: sqlite3.Connection, room_id: str, statuses: tuple[str, ...] = ()) -> list[sqlite3.Row]:
    where = f" AND status IN ({','.join('?' * len(statuses))})" if statuses else ""
    sql = f"SELECT * FROM hosted_room_driver_tasks WHERE room_id=?{where} {_TASK_ORDER}"
    return conn.execute(sql, (room_id, *statuses)).fetchall()


def _load_active_room(conn: sqlite3.Connection, room_id: str) -> sqlite3.Row:
    try:
        row = conn.execute(
            "SELECT room_id, authority_gateway_id, authority_epoch, disbanded_at FROM hosted_rooms WHERE room_id=?",
            (room_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            raise RoomUnavailableError("hosted room does not exist") from exc
        raise
    if row is None or row["disbanded_at"] is not None:
        raise RoomUnavailableError("hosted room does not exist" if row is None else "hosted room is disbanded")
    return row


def _require_room_authority(conn: sqlite3.Connection, room_id: str, gateway_id: str, epoch: int) -> sqlite3.Row:
    room = _load_active_room(conn, room_id)
    if room["authority_gateway_id"] != gateway_id or int(room["authority_epoch"]) != epoch:
        raise StaleLeaseError("hosted room authority changed")
    return room






def _require_active_lease(
    conn: sqlite3.Connection, lease: DriverLease, *, now: float, allow_expired: bool = False
) -> sqlite3.Row:
    """Authority match + lease-row generation match + unreleased must hold; ``allow_expired``
    additionally tolerates plain expiry of our own lease (live first-party settlement only)."""
    _require_room_authority(conn, lease.room_id, lease.gateway_id, lease.authority_epoch)
    row = conn.execute(_SELECT_LEASE, (lease.room_id,)).fetchone()
    if not _lease_row_matches(row, lease) or row["released_at"] is not None or (
        not allow_expired and float(row["expires_at"]) <= now
    ):
        raise StaleLeaseError("driver lease is stale or expired")
    return row


















def _transition(
    db_path: DbPath, identity: TaskIdentity, *, sql: str, set_params: tuple[Any, ...], fence_params: tuple[Any, ...],
    stale: str, now: float, lease: DriverLease | None = None, lease_first: bool = True,
    replay: Callable[[sqlite3.Row], dict[str, Any] | None] | None = None,
    guard: Callable[[sqlite3.Row], None] | None = None,
    allow_expired_lease: bool = False) -> dict[str, Any]:
    """Run one fenced task transition: load -> idempotent replay -> lease/fence guard -> UPDATE.

    ``sql`` binds ``(*set_params, room_id, task_id, *fence_params)`` and must hit exactly one row or ``stale``
    is raised. ``lease_first`` checks the lease before the row load (recovery paths) instead of after the
    replay (settlement paths: an identical replay still succeeds after the lease moved on);
    ``allow_expired_lease`` relaxes only that post-replay check and never the lease-first one.
    """
    params = (*set_params, identity.room_id, identity.task_id, *fence_params)
    with _transaction(db_path) as conn:
        if lease is not None and lease_first:
            _require_active_lease(conn, lease, now=now)
        row = _load_task(conn, identity)
        if replay is not None and (replayed := replay(row)) is not None:
            return replayed
        if lease is not None and not lease_first:
            _require_active_lease(conn, lease, now=now, allow_expired=allow_expired_lease)
        if guard is not None:
            guard(row)
        fenced_update(conn, sql, params, StaleTaskError(stale))
        from gateway.hosted_room_work_records import capture_transition_locked
        capture_transition_locked(conn, identity.room_id)
        return _task_from_row(_load_task(conn, identity))


def _generation_transition(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, name: str, execution_generation: int,
    cancel_generation: int, *, now: float, set_params: tuple[Any, ...],
    replay: Callable[[sqlite3.Row], Any] | None = None) -> dict[str, Any]:
    """Lease-first transition from ``_GENERATION_TRANSITIONS`` fenced on status + both generations."""
    status, set_clause, generation_stale, stale = _GENERATION_TRANSITIONS[name]
    def guard(row: sqlite3.Row) -> None:
        if not _generations_match(row, status, execution_generation, cancel_generation):
            raise StaleTaskError(generation_stale)
    return _transition(
        db_path, identity, lease=lease, now=now, replay=replay, guard=guard, sql=_generation_update(set_clause, status),
        set_params=set_params, fence_params=(execution_generation, cancel_generation), stale=stale)


def _run_fence_transition(
    db_path: DbPath, attempt: TaskAttempt, *, guard_stale: str, lease_generation: Callable[[Any], int] = int,
    **transition: Any) -> dict[str, Any]:
    """Transition fenced on this attempt's running generation under its exact lease (row guard + SQL fence).
    ``lease_generation`` casts the stored run_lease_generation: ``int`` raises on NULL, ``int(v or 0)`` reads 0."""
    lease = attempt.lease
    def guard(row: sqlite3.Row) -> None:
        if not _generations_match(row, "running", attempt.execution_generation, attempt.cancel_generation) or (
            row["run_gateway_id"], row["run_process_generation"], lease_generation(row["run_lease_generation"])
        ) != _run_fence(lease):
            raise StaleTaskError(guard_stale)
    return _transition(
        db_path, attempt.identity, lease=lease, guard=guard,
        fence_params=(attempt.execution_generation, attempt.cancel_generation, *_run_fence(lease)), **transition)


@room_operation("room_leases")
def acquire_lease(
    db_path: DbPath, *, room_id: Any, gateway_id: Any, authority_epoch: Any, process_generation: Any, ttl_seconds: Any,
    clock: Clock) -> DriverLease:
    """Acquire an empty or expired room lease with a monotonic generation."""
    room_id = _identifier(room_id, label="room_id")
    gateway_id = _identifier(gateway_id, label="gateway_id")
    authority_epoch = _bounded_int(authority_epoch, message="authority_epoch must be a positive integer", low=1)
    process_generation = _identifier(process_generation, label="process_generation")
    now, expires_at = _lease_window(ttl_seconds, clock)
    with _transaction(db_path) as conn:
        _require_room_authority(conn, room_id, gateway_id, authority_epoch)
        row = conn.execute(_SELECT_LEASE, (room_id,)).fetchone()
        if row is None:
            conn.execute("""INSERT INTO hosted_room_driver_leases (
                       room_id, gateway_id, authority_epoch, process_generation, lease_generation,
                       expires_at, acquired_at, updated_at, released_at
                   ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, NULL)""",
                (room_id, gateway_id, authority_epoch, process_generation, expires_at, now, now))
            return _lease_from_row(conn.execute(_SELECT_LEASE, (room_id,)).fetchone())
        same_authority = row["gateway_id"] == gateway_id and int(row["authority_epoch"]) == authority_epoch
        live = row["released_at"] is None and float(row["expires_at"]) > now
        if same_authority and row["process_generation"] == process_generation and live:
            renewed_expiry = max(float(row["expires_at"]), expires_at)
            conn.execute(
                "UPDATE hosted_room_driver_leases SET expires_at=?, updated_at=? WHERE room_id=? AND lease_generation=?",
                (renewed_expiry, now, room_id, int(row["lease_generation"])))
            return _lease_from_row({**dict(row), "expires_at": renewed_expiry})
        if same_authority and live:
            raise LeaseHeldError("room driver lease is held by another generation")
        fenced_update(conn, """UPDATE hosted_room_driver_leases
               SET gateway_id=?, authority_epoch=?, process_generation=?, lease_generation=lease_generation + 1,
                   expires_at=?, acquired_at=?, updated_at=?, released_at=NULL
               WHERE room_id=? AND lease_generation=? AND (
                   gateway_id != ? OR authority_epoch != ? OR released_at IS NOT NULL OR expires_at <= ?)""",
            (
                gateway_id, authority_epoch, process_generation, expires_at, now, now, room_id,
                int(row["lease_generation"]), gateway_id, authority_epoch, now),
            LeaseHeldError("room driver lease changed during acquisition"))
        return _lease_from_row(conn.execute(_SELECT_LEASE, (room_id,)).fetchone(), reclaimed=True)


@room_operation("room_leases")
def renew_lease(db_path: DbPath, lease: DriverLease, *, ttl_seconds: Any, clock: Clock) -> DriverLease:
    """Renew the exact active lease generation or fail closed."""
    now, requested_expiry = _lease_window(ttl_seconds, clock)
    with _transaction(db_path) as conn:
        current = _require_active_lease(conn, lease, now=now)
        expires_at = max(float(current["expires_at"]), requested_expiry)
        fenced_update(conn, """UPDATE hosted_room_driver_leases SET expires_at=?, updated_at=?
               WHERE room_id=? AND gateway_id=? AND process_generation=?
                 AND lease_generation=? AND released_at IS NULL AND expires_at > ?""",
            (expires_at, now, lease.room_id, *_run_fence(lease), now),
            StaleLeaseError("driver lease changed during renewal"))
        return dataclasses.replace(lease, expires_at=expires_at, reclaimed=False)


@room_operation("room_leases")
def release_lease(db_path: DbPath, lease: DriverLease, *, clock: Clock) -> dict[str, Any]:
    """Release the exact active lease generation idempotently."""
    now = _timestamp(clock)
    with _transaction(db_path) as conn:
        _require_room_authority(conn, lease.room_id, lease.gateway_id, lease.authority_epoch)
        row = conn.execute(_SELECT_LEASE, (lease.room_id,)).fetchone()
        if not _lease_row_matches(row, lease):
            raise StaleLeaseError("driver lease is stale")
        if row["released_at"] is not None:
            return {"lease": _lease_from_row(row), "idempotent": True}
        if float(row["expires_at"]) <= now:
            raise StaleLeaseError("driver lease expired before release")
        if conn.execute(
            "SELECT 1 FROM hosted_room_driver_tasks WHERE room_id=? AND status='running' LIMIT 1", (lease.room_id,)
        ).fetchone() is not None:
            raise InvalidTaskTransitionError("cannot release a room lease while tasks are running")
        conn.execute("""UPDATE hosted_room_driver_leases SET expires_at=?, updated_at=?, released_at=?
               WHERE room_id=? AND lease_generation=?""",
            (now, now, now, lease.room_id, lease.lease_generation))
        return {
            "lease": _lease_from_row({**dict(row), "expires_at": now, "updated_at": now, "released_at": now}),
            "idempotent": False}


@room_operation("room_runs")
def admit_task(db_path: DbPath, identity: TaskIdentity, *, payload: Any, clock: Clock) -> dict[str, Any]:
    """Persist a queued task, or return the identical admission."""
    normalized_payload, payload_json, payload_digest = _task_payload(payload)
    now = _timestamp(clock)
    with _transaction(db_path) as conn:
        _load_active_room(conn, identity.room_id)
        existing = _load_task(conn, identity, required=False)
        if existing is not None:
            if existing["payload_digest"] != payload_digest or existing["payload_json"] != payload_json:
                raise TaskConflictError("task_id is already bound to a different payload")
            return _task_from_row(existing, idempotent=True)
        if conn.execute(
            "SELECT * FROM hosted_room_driver_tasks WHERE room_id=? AND thread_id=? AND turn_id=?",
            (identity.room_id, identity.thread_id, identity.turn_id)).fetchone() is not None:
            raise TaskConflictError("thread_id and turn_id are already bound to a task")
        conn.execute("""INSERT INTO hosted_room_driver_tasks (
                   room_id, task_id, thread_id, turn_id, source_event_seq, payload_json, payload_digest,
                   status, execution_generation, cancel_generation, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 0, 0, ?, ?)""",
            (
                *dataclasses.astuple(identity), normalized_payload["source_event_seq"], payload_json, payload_digest,
                now, now))
        from gateway.hosted_room_work_records import capture_transition_locked
        capture_transition_locked(conn, identity.room_id)
        return _task_from_row(_load_task(conn, identity))


@room_operation("room_runs")
def start_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_cancel_generation: int, clock: Clock
) -> TaskAttempt:
    """Move one queued task to running under the current driver lease."""
    _check_same_room(lease, identity)
    _cancel_generation(expected_cancel_generation)
    now = _timestamp(clock)
    with _transaction(db_path) as conn:
        _require_active_lease(conn, lease, now=now)
        row = _load_task(conn, identity)
        _require_cancel_generation(row, expected_cancel_generation)
        if row["status"] != "queued":
            raise InvalidTaskTransitionError(f"cannot start task in state '{row['status']}'")
        if conn.execute(
            f"""SELECT task_id, status FROM hosted_room_driver_tasks
               WHERE room_id=? AND status IN ('running', 'indeterminate', 'stopping') {_TASK_ORDER} LIMIT 1""",
            (identity.room_id,)).fetchone() is not None:
            raise InvalidTaskTransitionError("room recovery must resolve the prior task before starting new work")
        next_queued = conn.execute(
            f"SELECT task_id FROM hosted_room_driver_tasks WHERE room_id=? AND status='queued' {_TASK_ORDER} LIMIT 1",
            (identity.room_id,)).fetchone()
        if next_queued is None or next_queued["task_id"] != identity.task_id:
            raise InvalidTaskTransitionError("task is not next in the hosted room event order")
        execution_generation = int(row["execution_generation"]) + 1
        fenced_update(conn, """UPDATE hosted_room_driver_tasks
               SET status='running', execution_generation=?, run_gateway_id=?, run_process_generation=?,
                   run_lease_generation=?, started_at=?, updated_at=?
               WHERE room_id=? AND task_id=? AND status='queued' AND cancel_generation=?""",
            (
                execution_generation, *_run_fence(lease), now, now, identity.room_id, identity.task_id,
                expected_cancel_generation), StaleTaskError("task changed during start"))
        from gateway.hosted_room_work_records import capture_transition_locked
        capture_transition_locked(conn, identity.room_id)
        return TaskAttempt(
            identity=identity, lease=lease, execution_generation=execution_generation,
            cancel_generation=expected_cancel_generation)


@room_operation("room_task_settlement")
def settle_task(
    db_path: DbPath, attempt: TaskAttempt, *, settlement_id: Any, status: TerminalStatus, result: Any, clock: Clock,
    allow_expired_lease: bool = False
) -> dict[str, Any]:
    """Commit one terminal result if every lease and task fence still matches.

    ``allow_expired_lease`` serves the live in-process terminal callback only: plain expiry of our
    own unreleased, un-reclaimed lease must not discard an already-completed first-party result, so
    the post-replay check drops only its ``expires_at > now`` term. Reclaim, release and authority
    transfer still fence; historical harvest paths keep the strict check.
    """
    now, replay, set_params = _settlement(settlement_id, status, result, clock)
    return _run_fence_transition(
        db_path, attempt, guard_stale="task attempt is stale or cancelled", lease_first=False, now=now, replay=replay,
        sql=_SETTLE_RUNNING_SQL, set_params=set_params, stale="task changed during settlement",
        allow_expired_lease=allow_expired_lease)


@room_operation("room_task_settlement")
def settle_stopping_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, settlement_id: Any, status: TerminalStatus, result: Any, clock: Clock
) -> dict[str, Any]:
    """Commit a completion that won the race with an unacknowledged Stop."""
    _terminal_settlement_id(settlement_id, status)  # settlement errors take precedence over generation errors
    if expected_execution_generation < 1 or expected_cancel_generation < 1:
        raise DriverValidationError("stopping settlement generations are invalid")
    now, replay, set_params = _settlement(settlement_id, status, result, clock)
    return _transition(
        db_path, identity, lease=lease, lease_first=False, now=now, replay=replay, sql=_SETTLE_STOPPING_SQL,
        set_params=set_params, fence_params=(expected_execution_generation, expected_cancel_generation),
        stale="task completion lost the stop race")


@room_operation("room_task_recovery")
def resolve_indeterminate_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, settlement_id: Any, status: TerminalStatus, result: Any, clock: Clock
) -> dict[str, Any]:
    """Commit a verified historical receipt under the current room lease."""
    _expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now, replay, set_params = _settlement(settlement_id, status, result, clock)
    return _generation_transition(
        db_path, identity, lease, "resolve", expected_execution_generation, expected_cancel_generation, now=now,
        replay=replay, set_params=set_params)


@room_operation("room_task_recovery")
def resolve_indeterminate_cancellation(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, cancel_id: Any, clock: Clock) -> dict[str, Any]:
    """Commit a verified terminal cancellation for an uncertain attempt."""
    _expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    cancel_id = _identifier(cancel_id, label="cancel_id")
    now = _timestamp(clock)
    return _generation_transition(
        db_path, identity, lease, "resolve_cancel", expected_execution_generation, expected_cancel_generation, now=now,
        replay=_cancel_replay(cancel_id), set_params=(expected_cancel_generation + 1, cancel_id, now, now))


@room_operation("room_task_recovery")
def requeue_indeterminate_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, clock: Clock) -> dict[str, Any]:
    """Explicitly retry uncertain work after an operator accepts at-least-once risk."""
    _expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = _timestamp(clock)
    return _generation_transition(
        db_path, identity, lease, "requeue", expected_execution_generation, expected_cancel_generation, now=now,
        set_params=(now,))


@room_operation("room_task_recovery")
def defer_indeterminate_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, reason: Any, clock: Clock) -> dict[str, Any]:
    """Fence one uncertain attempt and release later room work."""
    return _defer(db_path, identity, lease, "defer", expected_execution_generation, expected_cancel_generation,
                  reason=reason, clock=clock)


@room_operation("room_task_recovery")
def defer_unconfirmed_stop(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, reason: Any, clock: Clock) -> dict[str, Any]:
    """Release later room work behind a Stop its member never confirmed: deferred, never cancelled."""
    return _defer(db_path, identity, lease, "defer_stopping", expected_execution_generation,
                  expected_cancel_generation, reason=reason, clock=clock)


def _defer(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, name: str, expected_execution_generation: int,
    expected_cancel_generation: int, *, reason: Any, clock: Clock) -> dict[str, Any]:
    _expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    reason = _identifier(reason, label="defer_reason")
    result_json = _canonical_json({"reason": reason, "retryable": True})
    now = _timestamp(clock)
    def replay(row: sqlite3.Row) -> dict[str, Any] | None:
        deferred = _generations_match(row, "deferred", expected_execution_generation, expected_cancel_generation)
        return _task_from_row(row, idempotent=True) if deferred and row["result_json"] == result_json else None
    return _generation_transition(
        db_path, identity, lease, name, expected_execution_generation, expected_cancel_generation, now=now,
        replay=replay, set_params=(result_json, now, now))


@room_operation("room_task_recovery")
def requeue_deferred_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, clock: Clock) -> dict[str, Any]:
    """Explicitly retry a fenced deferred turn under a new generation."""
    _expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = _timestamp(clock)
    return _generation_transition(
        db_path, identity, lease, "requeue_deferred", expected_execution_generation, expected_cancel_generation,
        now=now, set_params=(now,))


@room_operation("room_task_recovery")
def reopen_deferred_task(
    db_path: DbPath, identity: TaskIdentity, lease: DriverLease, *, expected_execution_generation: int,
    expected_cancel_generation: int, clock: Clock) -> dict[str, Any]:
    """Return a deferred turn to indeterminate at its same generation (its peer still owns that generation).
    The retry restarts the attempt's clock: its time limit counts from now, not from the first start."""
    _expected_generations(lease, identity, expected_execution_generation, expected_cancel_generation)
    now = _timestamp(clock)
    return _generation_transition(
        db_path, identity, lease, "reopen_deferred", expected_execution_generation, expected_cancel_generation,
        now=now, set_params=(now, now, now))


@room_operation("room_task_settlement")
def requeue_not_admitted_task(db_path: DbPath, attempt: TaskAttempt, *, clock: Clock) -> dict[str, Any]:
    """Return a running task to its durable queue after proven non-admission."""
    now = _timestamp(clock)
    _check_same_room(attempt.lease, attempt.identity)
    def replay(row: sqlite3.Row) -> dict[str, Any] | None:
        requeued = _generations_match(row, "queued", attempt.execution_generation, attempt.cancel_generation) and (
            row["run_gateway_id"], row["run_process_generation"], row["run_lease_generation"]) == (None, None, None)
        return _task_from_row(row, idempotent=True) if requeued else None
    return _run_fence_transition(
        db_path, attempt, guard_stale="not-admitted task attempt lost its fence",
        lease_generation=lambda value: int(value or 0), now=now, replay=replay, sql=_REQUEUE_RUNNING_SQL,
        set_params=(now,), stale="not-admitted task changed during requeue")


@room_operation("room_task_settlement")
def cancel_task(
    db_path: DbPath, identity: TaskIdentity, *, cancel_id: Any, expected_cancel_generation: int, clock: Clock
) -> dict[str, Any]:
    """Cancel a queued task before any external work was admitted."""
    cancel_id = _identifier(cancel_id, label="cancel_id")
    _cancel_generation(expected_cancel_generation)
    now = _timestamp(clock)
    def guard(row: sqlite3.Row) -> None:
        if row["status"] in TERMINAL_STATUSES:
            raise InvalidTaskTransitionError(f"cannot cancel task in state '{row['status']}'")
        if row["status"] not in {"queued", "deferred"}:
            raise InvalidTaskTransitionError("running work requires acknowledged two-phase cancellation")
        _require_cancel_generation(row, expected_cancel_generation)
    return _transition(
        db_path, identity, now=now, replay=_cancel_replay(cancel_id), guard=guard, sql=_CANCEL_QUEUED_SQL,
        set_params=(expected_cancel_generation + 1, cancel_id, now, now), fence_params=(expected_cancel_generation,),
        stale="task changed during cancellation")


@room_operation("room_task_settlement")
def begin_task_cancel(
    db_path: DbPath, identity: TaskIdentity, *, cancel_id: Any, expected_cancel_generation: int, clock: Clock
) -> dict[str, Any]:
    """Persist a stop intent without claiming the remote run has stopped."""
    cancel_id = _identifier(cancel_id, label="cancel_id")
    _cancel_generation(expected_cancel_generation)
    now = _timestamp(clock)
    def guard(row: sqlite3.Row) -> None:
        if row["status"] in TERMINAL_STATUSES or row["status"] == "queued":
            raise InvalidTaskTransitionError(f"cannot request remote stop in state '{row['status']}'")
        _require_cancel_generation(row, expected_cancel_generation)
    return _transition(
        db_path, identity, now=now, replay=_cancel_replay(cancel_id, "stopping"), guard=guard, sql=_BEGIN_STOP_SQL,
        set_params=(expected_cancel_generation + 1, cancel_id, now), fence_params=(expected_cancel_generation,),
        stale="task changed during stop request")


@room_operation("room_task_settlement")
def complete_task_cancel(
    db_path: DbPath, identity: TaskIdentity, *, cancel_id: Any, expected_cancel_generation: int, clock: Clock
) -> dict[str, Any]:
    """Commit cancellation only after the transport acknowledges exact Stop."""
    cancel_id = _identifier(cancel_id, label="cancel_id")
    now = _timestamp(clock)
    def guard(row: sqlite3.Row) -> None:
        if (row["status"], row["cancel_id"], int(row["cancel_generation"])) != (
            "stopping", cancel_id, expected_cancel_generation):
            raise StaleTaskError("task stop acknowledgement is stale")
    return _transition(
        db_path, identity, now=now, replay=_cancel_replay(cancel_id), guard=guard, sql=_COMPLETE_STOP_SQL,
        set_params=(now, now), fence_params=(cancel_id, expected_cancel_generation),
        stale="task changed during stop acknowledgement")


@room_operation("room_runs")
def mark_attempt_indeterminate(
    db_path: DbPath, attempt: TaskAttempt, lease: DriverLease, *, clock: Clock
) -> None:
    """Retire exactly the unwatched attempt, even if another control renewed its lease."""
    _check_same_room(lease, attempt.identity)
    now = _timestamp(clock)
    with _transaction(db_path) as conn:
        _require_active_lease(conn, lease, now=now)
        row = _load_task(conn, attempt.identity)
        if not _generations_match(row, "running", attempt.execution_generation, attempt.cancel_generation):
            return
        conn.execute(
            _generation_update("status='indeterminate', indeterminate_at=?, updated_at=?", "running"),
            (now, now, attempt.identity.room_id, attempt.identity.task_id,
             attempt.execution_generation, attempt.cancel_generation))
        from gateway.hosted_room_work_records import capture_transition_locked
        capture_transition_locked(conn, lease.room_id)


@room_operation("room_runs")
def recover_room(db_path: DbPath, lease: DriverLease, *, clock: Clock) -> dict[str, list[TaskIdentity]]:
    """Fence abandoned running attempts without requeueing uncertain work."""
    now = _timestamp(clock)
    foreign_running = f"room_id=? AND status='running' AND NOT ({_RUN_FENCE})"
    fence = (lease.room_id, *_run_fence(lease))
    with _transaction(db_path) as conn:
        _require_active_lease(conn, lease, now=now)
        stale_rows = conn.execute(
            f"SELECT * FROM hosted_room_driver_tasks WHERE {foreign_running} {_TASK_ORDER}", fence).fetchall()
        if stale_rows:
            conn.execute(
                f"""UPDATE hosted_room_driver_tasks SET status='indeterminate', indeterminate_at=?, updated_at=?
                    WHERE {foreign_running}""", (now, now, *fence))
        from gateway.hosted_room_work_records import capture_transition_locked
        capture_transition_locked(conn, lease.room_id)
        return {
            status: [_task_identity_from_row(row) for row in _tasks_in_order(conn, lease.room_id, (status,))]
            for status in ("queued", "indeterminate")}


@room_operation("room_runs")
def get_task(db_path: DbPath, identity: TaskIdentity) -> dict[str, Any]:
    """Read one task without mutating its state."""
    with closing(_connect(db_path)) as conn:
        return _task_from_row(_load_task(conn, identity))


@room_operation("room_runs")
def list_tasks(db_path: DbPath, *, room_id: Any, status: TaskStatus | None = None) -> list[dict[str, Any]]:
    """Return room tasks in deterministic admission order."""
    room_id = _identifier(room_id, label="room_id")
    if status is not None and status not in TASK_STATUSES:
        raise DriverValidationError("invalid task status")
    with closing(_connect(db_path)) as conn:
        return [_task_from_row(row) for row in _tasks_in_order(conn, room_id, () if status is None else (status,))]


@room_operation("room_runs")
def room_task_summary(
        db_path: DbPath, *, room_id: Any, statuses: Iterable[str]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """``({status: count}, tasks in those statuses, in admission order)`` for one room from one read
    snapshot: retained terminal tasks are only counted (status index), never decoded."""
    room_id = _identifier(room_id, label="room_id")
    statuses = tuple(statuses)
    if any(status not in TASK_STATUSES for status in statuses):
        raise DriverValidationError("invalid task status")
    with closing(_connect(db_path)) as conn, conn:
        # Python's sqlite3 runs SELECTs in autocommit; the explicit BEGIN makes both reads one WAL snapshot,
        # so a task moving between them is neither doubled nor lost. ``with conn`` ends it.
        conn.execute("BEGIN")
        counts = {str(status): int(count) for status, count in conn.execute(
            "SELECT status, COUNT(*) FROM hosted_room_driver_tasks WHERE room_id=? GROUP BY status", (room_id,))}
        rows = _tasks_in_order(conn, room_id, statuses) if statuses else []
    return counts, [_task_from_row(row) for row in rows]


def room_change_rows(conn: sqlite3.Connection, statuses: tuple[str, ...] = SHOWN_TASK_STATUSES) -> dict[str, RoomChangeRows]:
    """Per live room in one store, what its log and ``groups.state`` read from the store, for a change
    signature: ``RoomChangeRows(next_seq, revision, ((task_id, status, execution_generation, cancel_generation), ...))``
    over the tasks in ``statuses``. ``next_seq`` moves on every append and ``revision`` on a rename,
    membership or authority edit; the generations move a Retry that keeps its status. A disbanded room is
    left out (its key going away is the change). Each room's rows are read through the status index
    (``room_id, status`` prefix) and sorted here: an ``ORDER BY task_id`` would make SQLite walk the room's
    retained terminal tasks through the primary key instead."""
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('hosted_rooms', 'hosted_room_driver_tasks')")}
    if "hosted_rooms" not in tables:
        return {}
    rooms = conn.execute("SELECT room_id, next_seq, revision FROM hosted_rooms WHERE disbanded_at IS NULL").fetchall()
    if "hosted_room_driver_tasks" not in tables:
        return {room_id: RoomChangeRows(next_seq, revision, ()) for room_id, next_seq, revision in rooms}
    query = f"""SELECT task_id, status, execution_generation, cancel_generation FROM hosted_room_driver_tasks
                WHERE room_id=? AND status IN ({','.join('?' * len(statuses))})"""
    return {room_id: RoomChangeRows(
                next_seq, revision, tuple(sorted(tuple(row) for row in conn.execute(query, (room_id, *statuses)))))
            for room_id, next_seq, revision in rooms}


@room_operation("room_task_retention")
def prune_published_terminal_tasks(
    db_path: DbPath, *, room_id: Any, clock: Clock, retention_seconds: float = TERMINAL_TASK_RETENTION_SECONDS,
    retain: int = MAX_RETAINED_TERMINAL_TASKS) -> int:
    """Bound execution rows after outcomes are durable in the room log."""
    room_id = _identifier(room_id, label="room_id")
    now = _timestamp(clock)
    if retention_seconds <= 0:
        raise DriverValidationError("retention_seconds must be positive")
    _bounded_int(retain, message="retain must be a non-negative integer")
    with _transaction(db_path) as conn:
        publications = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_room_policy_publications'").fetchone()
        if publications is None:
            return 0
        rows = conn.execute("""SELECT t.task_id, t.terminal_at FROM hosted_room_driver_tasks t
                WHERE t.room_id=? AND t.status IN ('settled', 'failed', 'cancelled')
                  AND EXISTS (SELECT 1 FROM hosted_room_policy_publications p
                              WHERE p.room_id=t.room_id AND p.task_id=t.task_id
                                AND p.kind IN ('turn.settled', 'turn.failed', 'turn.cancelled'))
                ORDER BY t.terminal_at DESC, t.task_id ASC""", (room_id,)).fetchall()
        cutoff = now - float(retention_seconds)
        candidates = [
            str(row["task_id"]) for index, row in enumerate(rows)
            if index >= retain or (row["terminal_at"] is not None and float(row["terminal_at"]) <= cutoff)
        ][:MAX_TASK_PRUNE_BATCH]
        if not candidates:
            return 0
        deleted = conn.execute(
            f"DELETE FROM hosted_room_driver_tasks WHERE room_id=? AND task_id IN ({','.join('?' * len(candidates))})",
            (room_id, *candidates))
        return max(0, int(deleted.rowcount))


@room_operation("room_runs")
def get_task_for_turn(
    db_path: DbPath,
    identity: TaskIdentity,
) -> dict[str, Any] | None:
    """Read the immutable admission for a turn, including older payload versions."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """SELECT * FROM hosted_room_driver_tasks
               WHERE room_id=? AND thread_id=? AND turn_id=?""",
            (identity.room_id, identity.thread_id, identity.turn_id),
        ).fetchone()
        return _task_from_row(row) if row is not None else None
    finally:
        conn.close()
