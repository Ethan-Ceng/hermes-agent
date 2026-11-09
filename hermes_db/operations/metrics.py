"""Metrics counters and latches commit atomically within the owning Profile."""

import json
from datetime import timedelta
from sqlalchemy import select
from hermes_db.repositories import metrics as repo
from hermes_db.tables.metrics import state, counters
from hermes_db.core.values import decode_text


def record(conn, store, metric, dimensions, resource, now, amount=1):
    repo.install_id(conn, store)
    repo.increment(conn, store, metric, dimensions, resource, now.date().isoformat(), amount)


def once(conn, store, state_key, metric, dimensions, resource, now, *, interval=False, daily=False):
    from hermes_cli.observability.shared_metrics import SharedMetricsStore, _isoformat
    previous = repo.get_state(conn, store, state_key)
    if interval:
        stamp = SharedMetricsStore._parse_state_timestamp(previous)
        if stamp is not None and stamp > now:
            repo.set_state(conn, store, state_key, _isoformat(now))
            return False
        if stamp is not None and now < stamp + timedelta(hours=24):
            return False
    elif previous is not None and (not daily or previous == now.date().isoformat()):
        return False
    record(conn, store, metric, dimensions, resource, now)
    repo.set_state(conn, store, state_key, now.date().isoformat() if daily else _isoformat(now))
    return True


def latched(conn, store, prefix):
    rows = conn.scalars(select(state.c.key).where(repo.scope(state, store)))
    return frozenset(name[len(prefix):] for raw in rows if (name := decode_text(raw)).startswith(prefix))


def rollup(conn, store, state_key, update):
    from hermes_cli.observability.shared_metrics import _compact_json
    from hermes_cli.observability.shared_metrics_contract import counter_dimensions_are_valid, client_resource_is_valid
    raw = repo.get_state(conn, store, state_key)
    try:
        previous = json.loads(raw) if raw is not None else None
    except (TypeError, ValueError):
        previous = None
    new_state, rows = update(previous if isinstance(previous, dict) else None)
    for metric, dimensions, resource, period in rows:
        if counter_dimensions_are_valid(metric, dimensions) and client_resource_is_valid(resource):
            repo.install_id(conn, store)
            repo.increment(conn, store, metric, dimensions, resource, period)
    repo.set_state(conn, store, state_key, _compact_json(new_state))


def snapshot(conn, store):
    rows = conn.execute(select(counters).where(repo.scope(counters, store)).order_by(*(counters.c[name] for name in (
        "period_start", "hermes_version", "os_family", "architecture", "install_method", "metric_name", "dimensions_json")))).mappings()
    return [dict(period_start=row["period_start"], metric_name=row["metric_name"],
        resource={name: row[name] for name in ("hermes_version", "os_family", "architecture", "install_method")},
        dimensions=json.loads(row["dimensions_json"]), value=row["value"], packaged_value=row["packaged_value"])
        for raw in rows if (row := repo.record(raw))]
