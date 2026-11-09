"""Short scoped attempt mutations, fenced ownership and post-commit observers."""

import os

from sqlalchemy import and_, select, tuple_

from hermes_db.domains.cron.postgres.queries import cron as repo
from hermes_db.tables.cron import cron_executions as executions
from hermes_db.core.values import encode_text


def _owned():
    from cron import executions as ex
    return and_(executions.c.process_id == encode_text(ex._PROCESS_ID), executions.c.pid == os.getpid())


def _active():
    return executions.c.status.in_(("claimed", "running"))


def _update(resource, execution_id, condition, values, *, prune=False, emit=True, finish=False):
    from cron import executions as ex
    with repo.write(resource) as conn:
        if not repo.update_execution(conn, resource.scope, execution_id, condition, values):
            return False, None
        if prune:
            repo.prune(conn, resource.scope, ex.MAX_TERMINAL_EXECUTIONS)
        record = repo.fetch(conn, executions, resource.scope, execution_id)
    if emit:
        ex._emit_execution_state(record, delivery_outcome=values.get("delivery_outcome"))
    if finish:
        ex.record_cron_finish(record, values.get("delivery_outcome"))
    return True, record


def _insert(resource, job_id, source, *, status="claimed", error=None, scheduled_instant=None):
    from cron import executions as ex
    from cron.occurrences import scheduled_instant as canonical
    now, execution_id, pid = ex._hermes_now().isoformat(), ex.uuid.uuid4().hex, os.getpid()
    values = {"id": execution_id, "job_id": str(job_id), "source": str(source), "process_id": ex._PROCESS_ID,
        "pid": pid, "process_started_at": ex._process_start_time(pid), "status": status,
        "claimed_at": now, "error": error, "scheduled_instant": canonical(scheduled_instant)}
    if status == "missed":
        values["finished_at"] = now
    with repo.write(resource) as conn:
        conn.execute(executions.insert().values(store_id=resource.scope.require_store_id(), **repo.encode(values)))
        if status == "missed":
            repo.prune(conn, resource.scope, ex.MAX_TERMINAL_EXECUTIONS)
        record = repo.fetch(conn, executions, resource.scope, execution_id)
    ex._emit_execution_state(record)
    return record


def create_execution(resource, job_id, *, source, scheduled_instant=None):
    return _insert(resource, job_id, source, scheduled_instant=scheduled_instant)


def record_missed_occurrences(resource, job_id, *, count, first_instant, detail):
    if count < 1:
        return None
    return _insert(resource, job_id, "scheduler", status="missed", error=f"missed ×{count} ({detail})",
                   scheduled_instant=first_instant)


def touch_execution_progress(resource, execution_id):
    from cron import executions as ex
    return _update(resource, execution_id, and_(_owned(), _active()),
                   {"progress_at": ex._hermes_now().isoformat()}, emit=False)[0]


def set_execution_occurrence(resource, execution_id, instant):
    from cron.occurrences import scheduled_instant
    changed, _record = _update(resource, execution_id,
        and_(_owned(), executions.c.status == "claimed", executions.c.handoff_pending == 0),
        {"scheduled_instant": scheduled_instant(instant)}, emit=False)
    if not changed:
        raise RuntimeError("Cron occurrence could not be bound before dispatch")


def mark_execution_handoff_pending(resource, execution_id):
    from cron import executions as ex
    return _update(resource, execution_id, and_(_owned(), executions.c.status == "claimed"),
                   {"handoff_pending": 1, "handoff_started_at": ex.time.time()})[1]


def adopt_claimed_execution(resource, execution_id):
    from cron import executions as ex
    pid = os.getpid()
    return _update(resource, execution_id, and_(executions.c.status == "claimed", executions.c.handoff_pending == 1),
        {"process_id": ex._PROCESS_ID, "pid": pid, "process_started_at": ex._process_start_time(pid),
         "status": "running", "started_at": ex._hermes_now().isoformat(), "handoff_pending": 0, "handoff_started_at": None})[1]


def mark_execution_running(resource, execution_id):
    from cron import executions as ex
    return _update(resource, execution_id,
        and_(_owned(), executions.c.status == "claimed", executions.c.handoff_pending == 0),
        {"status": "running", "started_at": ex._hermes_now().isoformat(), "handoff_pending": 0, "handoff_started_at": None})[1]


def finish_execution(resource, execution_id, *, success, error=None, delivery_outcome=None, cancelled=False):
    from cron import executions as ex
    return _update(resource, execution_id, and_(_owned(), _active()),
        {"status": "cancelled" if cancelled else "completed" if success else "failed",
         "finished_at": ex._hermes_now().isoformat(), "error": None if success else str(error) if error else "unknown failure",
         "handoff_pending": 0, "handoff_started_at": None, "delivery_outcome": delivery_outcome}, prune=True, finish=True)[1]


def give_up_execution(resource, execution_id, *, reason):
    from cron import executions as ex
    return _update(resource, str(execution_id), and_(_owned(), _active()),
        {"status": "unknown", "finished_at": ex._hermes_now().isoformat(), "error": reason,
         "handoff_pending": 0, "handoff_started_at": None}, prune=True)[0]


def settle_delivery_outcome(resource, execution_id, outcome):
    return _update(resource, execution_id, and_(executions.c.delivery_outcome == encode_text("queued"),
        executions.c.status.in_(("completed", "failed", "unknown"))), {"delivery_outcome": outcome}, emit=False)[0]


def get_execution(resource, execution_id):
    with resource.read() as conn:
        return repo.fetch(conn, executions, resource.scope, str(execution_id))


def list_executions(resource, *, job_id=None, limit=50, before_claimed_at=None):
    query = select(executions).where(repo.scoped(executions, resource.scope))
    if job_id is not None:
        query = query.where(executions.c.job_id == encode_text(str(job_id)))
    if before_claimed_at is not None:
        query = query.where(tuple_(executions.c.claimed_order, executions.c.claimed_at) <
                            tuple_(repo.instant_order(str(before_claimed_at)), str(before_claimed_at)))
    with resource.read() as conn:
        return repo.rows(conn, query.order_by(*repo.execution_order()).limit(max(1, min(int(limit), 500))))


def live_inflight_execution(resource, job_id):
    from cron import executions as ex
    with resource.read() as conn:
        query = select(executions).where(repo.scoped(executions, resource.scope),
            executions.c.job_id == encode_text(job_id), executions.c.status != "missed")
        rows = repo.rows(conn, query.order_by(*repo.execution_order()).limit(1))
    record = rows[0] if rows else None
    return record if record and record["status"] in ("claimed", "running") and ex._owner_is_live(
        int(record["pid"]), record["process_started_at"]) else None


def _jobs(resource, job_ids, *, live):
    from cron import executions as ex
    clean = [str(job_id) for job_id in dict.fromkeys(job_ids) if job_id]
    if not clean:
        return {}
    query = select(executions).where(repo.scoped(executions, resource.scope),
                                     executions.c.job_id.in_([encode_text(job_id) for job_id in clean]))
    if live:
        query = query.where(_active())
    with resource.read() as conn:
        rows = repo.rows(conn, query.order_by(*repo.execution_order()))
    result = {}
    for row in rows:
        if row["job_id"] not in result and (not live or ex._row_owner_live(row)):
            result[row["job_id"]] = row
    return result


def live_executions(resource, job_ids):
    return _jobs(resource, job_ids, live=True)


def latest_executions(resource, job_ids):
    return _jobs(resource, job_ids, live=False)


def _recoverable(row, job_id):
    return row is not None and row["job_id"] == str(job_id) and row["status"] in ("claimed", "running", "unknown")


def execution_owner_live(resource, execution_id, job_id):
    from cron import executions as ex
    row = get_execution(resource, execution_id)
    return _recoverable(row, job_id) and ex._row_owner_live(row)


def recover_receipted_execution(resource, execution_id, job_id, *, success, error=None, delivery_outcome=None):
    from cron import executions as ex
    row = get_execution(resource, execution_id)
    if not _recoverable(row, job_id) or ex._row_owner_live(row):
        return None
    return _update(resource, execution_id, repo.snapshot_condition(row),
        {"status": "completed" if success else "failed", "finished_at": ex._hermes_now().isoformat(),
         "error": None if success else str(error) if error else "unknown failure", "handoff_pending": 0,
         "handoff_started_at": None, "delivery_outcome": delivery_outcome}, prune=True, finish=True)[1]


def _handoff_grace(row):
    from cron import executions as ex
    return row["handoff_pending"] and row["handoff_started_at"] is not None and (
        ex.time.time() - float(row["handoff_started_at"]) < ex.HANDOFF_ADOPTION_GRACE_SECONDS)


def terminalize_dead_owner(resource, execution_id, *, reason):
    from cron import executions as ex
    row = get_execution(resource, execution_id)
    if row is None or row["status"] not in ("claimed", "running") or row["process_id"] == ex._PROCESS_ID:
        return False
    if ex._owner_is_live(int(row["pid"]), row["process_started_at"]) or _handoff_grace(row):
        return False
    return _update(resource, execution_id, repo.snapshot_condition(row),
        {"status": "unknown", "finished_at": ex._hermes_now().isoformat(), "error": reason,
         "handoff_pending": 0, "handoff_started_at": None}, prune=True)[0]


def recover_interrupted_executions(resource):
    from cron import executions as ex
    with resource.read() as conn:
        rows = repo.rows(conn, select(executions).where(repo.scoped(executions, resource.scope), _active()))
    changed, stale_after, resolved = 0, None, False
    for row in rows:
        if row["process_id"] == ex._PROCESS_ID:
            continue
        reason = ex._OWNER_GONE_REASON
        if ex._owner_is_live(int(row["pid"]), row["process_started_at"]):
            if not resolved:
                stale_after, resolved = ex._live_owner_stale_after_seconds(), True
            if stale_after is None or ex._stale_age_seconds(row["claimed_at"], row["progress_at"]) <= stale_after:
                continue
            reason = ex._OWNER_WEDGED_REASON
        if _handoff_grace(row):
            continue
        changed += _update(resource, row["id"], repo.snapshot_condition(row),
            {"status": "unknown", "finished_at": ex._hermes_now().isoformat(), "error": reason,
             "handoff_pending": 0, "handoff_started_at": None}, prune=True)[0]
    return changed


def completed_occurrence_rows(resource, job_id, instant):
    with resource.read() as conn:
        return repo.rows(conn, select(executions).where(repo.scoped(executions, resource.scope),
            executions.c.job_id == encode_text(str(job_id)), executions.c.scheduled_instant == instant,
            executions.c.status == "completed"))
