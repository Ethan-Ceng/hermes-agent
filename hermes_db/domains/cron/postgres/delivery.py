"""Durable sends: scope-fenced claims, no retry after an uncertain send."""

from contextlib import contextmanager
import json
import os

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.cron.postgres.executions import _instant_order as instant_order
from hermes_db.tables.cron_delivery import cron_deliveries as rows, cron_delivery_tombstones as tombs, cron_delivery_locks as locks
from hermes_db.core.values import decode_text, encode_text

_EXACT = {"execution_id", "job_json", "content", "owner_process_id", "error"}


def _scope(table, resource):
    return table.c.store_id == resource.scope.require_store_id()


def _key(table, resource, execution_id):
    return and_(_scope(table, resource), table.c.execution_id == encode_text(str(execution_id)))


def _decode(row):
    return None if row is None else {key: decode_text(value) if key in _EXACT else value for key, value in row.items()
                                    if key not in ("store_id", "created_order", "finished_order")}


def _fetch(conn, resource, execution_id):
    return _decode(conn.execute(select(rows).where(_key(rows, resource, execution_id))).mappings().one_or_none())


@contextmanager
def _write(resource):
    with resource.write() as conn:
        conn.execute(insert(locks).values(store_id=resource.scope.require_store_id()).on_conflict_do_nothing())
        conn.execute(select(locks.c.store_id).where(_scope(locks, resource)).with_for_update()).one()
        yield conn


def _prune(conn, resource):
    queue = resource.delivery
    terminal = and_(_scope(rows, resource), rows.c.status.in_(queue.terminal))
    conn.execute(update(rows).where(terminal).values(job_json=encode_text("{}"), content=encode_text("")))
    excess = conn.execute(select(rows).where(terminal).order_by(rows.c.finished_order.desc().nulls_last(),
        rows.c.finished_at.desc(), rows.c.created_order.desc(), rows.c.created_at.desc(), rows.c.execution_id.desc())
        .offset(max(0, int(queue.max_terminal)))).mappings().all()
    if excess:
        conn.execute(insert(tombs).values([{"store_id": resource.scope.require_store_id(), "execution_id": row["execution_id"],
            "terminal_status": row["status"], "finished_at": row["finished_at"]} for row in excess]).on_conflict_do_nothing())
        conn.execute(delete(rows).where(_scope(rows, resource), rows.c.execution_id.in_([row["execution_id"] for row in excess])))


def enqueue(resource, execution_id, job, content, *, for_failure=False):
    queue = resource.delivery
    with _write(resource) as conn:
        tomb = conn.execute(select(tombs).where(_key(tombs, resource, execution_id))).mappings().one_or_none()
        if tomb is not None:
            return {"execution_id": str(execution_id), "status": tomb["terminal_status"], "finished_at": tomb["finished_at"]}
        now = queue.now().isoformat()
        conn.execute(insert(rows).values(store_id=resource.scope.require_store_id(), execution_id=encode_text(str(execution_id)),
            job_json=encode_text(json.dumps(job, ensure_ascii=False, sort_keys=True)), content=encode_text(str(content)),
            for_failure=int(bool(for_failure)), status="pending", created_at=now, created_order=instant_order(now))
            .on_conflict_do_nothing())
        return _fetch(conn, resource, execution_id)


def get_status(resource, execution_id):
    with resource.read() as conn:
        row = _fetch(conn, resource, execution_id)
        if row is not None:
            return row
        tomb = conn.execute(select(tombs).where(_key(tombs, resource, execution_id))).mappings().one_or_none()
        return None if tomb is None else {"execution_id": decode_text(tomb["execution_id"]), "status": tomb["terminal_status"],
                                          "finished_at": tomb["finished_at"], "error": None}


def claim_next(resource):
    queue = resource.delivery
    pid = os.getpid()
    started = queue.process_start_time(pid)
    with _write(resource) as conn:
        execution_id = conn.scalar(select(rows.c.execution_id).where(_scope(rows, resource), rows.c.status == "pending")
                                  .order_by(rows.c.created_order, rows.c.created_at, rows.c.execution_id).limit(1).with_for_update())
        if execution_id is None:
            return None
        conn.execute(update(rows).where(_scope(rows, resource), rows.c.execution_id == execution_id, rows.c.status == "pending")
            .values(status="delivering", owner_process_id=encode_text(queue.process_id), owner_pid=pid, owner_started_at=started))
        claimed = _fetch(conn, resource, decode_text(execution_id))
    queue.mark_active(claimed["execution_id"], resource.scope.profile_home)
    claimed["job"] = json.loads(claimed.pop("job_json"))
    return claimed


def _finish(resource, execution_id, *, error, suppressed=False):
    queue = resource.delivery
    now = queue.now().isoformat()
    safe_error = queue.redact_error(str(error), force=True, redact_url_credentials=True) if error else None
    with _write(resource) as conn:
        count = conn.execute(update(rows).where(_key(rows, resource, execution_id), rows.c.status == "delivering",
            rows.c.owner_process_id == encode_text(queue.process_id), rows.c.owner_pid == os.getpid())
            .values(status="failed" if error else "suppressed" if suppressed else "delivered", finished_at=now,
                    finished_order=instant_order(now), error=encode_text(safe_error))).rowcount
        _prune(conn, resource)
    return count == 1


def recover_abandoned(resource):
    queue = resource.delivery
    with resource.read() as conn:
        candidates = [_decode(row) for row in conn.execute(select(rows).where(_scope(rows, resource), rows.c.status == "delivering")).mappings()]
    fenced = []
    for row in candidates:
        same_process = row["owner_process_id"] == queue.process_id
        if same_process:
            if queue.is_active(row["execution_id"], resource.scope.profile_home):
                continue
        elif queue.owner_is_live(int(row["owner_pid"]), row["owner_started_at"]):
            continue
        error = ("Gateway finished delivery but could not persist its outcome; send was not retried." if same_process else
                 "Gateway exited during delivery; send outcome is unknown and was not retried.")
        now = queue.now().isoformat()
        with _write(resource) as conn:
            changed = conn.execute(update(rows).where(_key(rows, resource, row["execution_id"]), rows.c.status == "delivering",
                rows.c.owner_process_id.is_not_distinct_from(encode_text(row["owner_process_id"])),
                rows.c.owner_pid.is_not_distinct_from(row["owner_pid"]), rows.c.owner_started_at.is_not_distinct_from(row["owner_started_at"]))
                .values(status="unknown", finished_at=now, finished_order=instant_order(now), error=encode_text(error))).rowcount
            _prune(conn, resource)
        if changed:
            fenced.append((json.loads(row["job_json"] or "{}").get("id"), row["execution_id"]))
    for job_id, execution_id in fenced:
        queue.settle(job_id, execution_id)
    return len(fenced)


def _terminalize_wait_timeout(resource, execution_id):
    queue = resource.delivery
    now = queue.now().isoformat()
    error = "timed out while gateway delivery was in progress; outcome is unknown and was not retried"
    with _write(resource) as conn:
        row = _fetch(conn, resource, execution_id)
        if row is not None and row["status"] == "pending":
            queue.logger.warning("Cron delivery %s: no live gateway within the wait budget; left queued for the next gateway", execution_id)
            return ""
        conn.execute(update(rows).where(_key(rows, resource, execution_id), rows.c.status == "delivering")
                     .values(status="unknown", finished_at=now, finished_order=instant_order(now), error=encode_text(error)))
        row = _fetch(conn, resource, execution_id)
        _prune(conn, resource)
    if row is None:
        return "timed out waiting for live gateway delivery"
    return "" if row["status"] in ("delivered", "suppressed") else str(row["error"] or f"delivery {row['status']}")
