"""Scoped attempt/incident records with explicit exact-text and sort projections."""

from contextlib import contextmanager
from datetime import datetime, UTC
import math

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.cron import cron_executions as executions, cron_incidents as incidents, cron_locks as locks
from hermes_db.core.values import decode_text, encode_text

_BYTES = {"id", "job_id", "source", "process_id", "error", "delivery_outcome", "failure_type", "output_file"}
_PROJECTIONS = {"claimed_order", "finished_order", "last_seen_order"}


def instant_order(value):
    if value is None:
        return None
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return math.floor(instant.timestamp() * 1000 + 0.5)


def scoped(table, scope):
    return table.c.store_id == scope.require_store_id()


def key(table, scope, record_id):
    return and_(scoped(table, scope), table.c.id == encode_text(str(record_id)))


def encode(values):
    result = {name: encode_text(value) if name in _BYTES else value for name, value in values.items()}
    for source, projection in (("claimed_at", "claimed_order"), ("finished_at", "finished_order"), ("last_seen_at", "last_seen_order")):
        if source in result:
            result[projection] = instant_order(result[source])
    return result


def decode(row):
    if row is None:
        return None
    return {name: decode_text(value) if name in _BYTES else value for name, value in row.items()
            if name != "store_id" and name not in _PROJECTIONS}


def fetch(conn, table, scope, record_id):
    return decode(conn.execute(select(table).where(key(table, scope, record_id))).mappings().one_or_none())


def rows(conn, query):
    return [decode(row) for row in conn.execute(query).mappings()]


@contextmanager
def write(resource):
    with resource.write() as conn:
        conn.execute(insert(locks).values(store_id=resource.scope.require_store_id()).on_conflict_do_nothing())
        conn.execute(select(locks.c.store_id).where(scoped(locks, resource.scope)).with_for_update()).one()
        yield conn


def update_execution(conn, scope, execution_id, condition, values):
    return conn.execute(update(executions).where(key(executions, scope, execution_id), condition)
                        .values(**encode(values))).rowcount == 1


def execution_order():
    return (executions.c.claimed_order.desc(), executions.c.claimed_at.desc(), executions.c.id.desc())


def prune(conn, scope, limit):
    from cron.executions import _TERMINAL_STATES
    retained = select(executions.c.id).where(scoped(executions, scope), executions.c.status.in_(_TERMINAL_STATES))
    retained = retained.order_by(executions.c.finished_order.desc().nulls_last(), executions.c.finished_at.desc(),
                                 *execution_order()).limit(max(0, int(limit)))
    conn.execute(delete(executions).where(scoped(executions, scope), executions.c.status.in_(_TERMINAL_STATES),
                                         executions.c.id.not_in(retained)))


def snapshot_condition(row):
    return and_(*(getattr(executions.c, name).is_not_distinct_from(encode({name: row[name]})[name]) for name in
                  ("status", "process_id", "pid", "handoff_pending", "handoff_started_at", "claimed_at", "progress_at")))
