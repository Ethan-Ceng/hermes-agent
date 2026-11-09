"""Package insert and counter watermarks share one short transaction."""

import uuid
from datetime import datetime, timedelta, UTC
from sqlalchemy import delete, select, update, exists, func
from hermes_db.domains.metrics.postgres.queries import metrics as repo
from hermes_db.tables.metrics import counters, packages, RESOURCE, COUNTER_KEY


def create_one(conn, store, now):
    from hermes_cli.observability.shared_metrics import SharedMetricsStore, _compact_json, _isoformat, _PACKAGE_SCHEMA_VERSION
    from hermes_cli.observability.shared_metrics_contract import client_resource_is_valid
    while True:
        first = conn.execute(select(counters).where(repo.scope(counters, store), counters.c.value > counters.c.packaged_value)
            .order_by(counters.c.period_start, *(counters.c[name] for name in RESOURCE)).limit(1)).mappings().one_or_none()
        if first is None or not first["period_start"]:
            return None
        group = {name: repo.record(first)[name] for name in ("period_start", *RESOURCE)}
        rows = [repo.record(row) for row in conn.execute(select(counters).where(repo.key(counters, store, group),
            counters.c.value > counters.c.packaged_value).order_by(counters.c.metric_name, counters.c.dimensions_json)).mappings()]
        resource = {name: group[name] for name in RESOURCE}
        if not client_resource_is_valid(resource):
            raise ValueError("Unsupported shared-metrics client resource")
        metrics = SharedMetricsStore._package_metrics(rows)
        if not metrics:
            mark_packaged(conn, store, rows)
            continue
        start = datetime.fromisoformat(group["period_start"]).replace(tzinfo=UTC)
        payload = dict(schema_version=_PACKAGE_SCHEMA_VERSION, package_id=str(uuid.uuid4()), install_id=repo.install_id(conn, store),
            period_start=_isoformat(start), period_end=_isoformat(start + timedelta(days=1)), generated_at=_isoformat(now), resource=resource, metrics=metrics)
        conn.execute(packages.insert().values(store_id=store.scope.require_store_id(), **repo.values(packages, dict(
            package_id=payload["package_id"], period_start=payload["period_start"], period_end=payload["period_end"],
            payload_json=_compact_json(payload), created_at=payload["generated_at"]))))
        repo.advance_mark(conn, store, "data", payload["period_end"])
        mark_packaged(conn, store, rows)
        return payload


def mark_packaged(conn, store, rows):
    for row in rows:
        conn.execute(update(counters).where(repo.key(counters, store, {name: row[name] for name in COUNTER_KEY})).values(packaged_value=counters.c.value))


def create_pending(conn, store, now, *, due=False):
    if due and conn.scalar(select(packages.c.package_id).where(repo.scope(packages, store),
            func.substr(packages.c.created_at, 1, 10) >= now.date().isoformat()).limit(1)) is not None:
        return
    while create_one(conn, store, now) is not None:
        pass


def pending_exports(conn, store):
    return [repo.record(row) for row in conn.execute(select(packages.c.package_id, packages.c.payload_json).where(
        repo.scope(packages, store), packages.c.exported_at.is_(None)).order_by(packages.c.created_at, packages.c.package_id)).mappings()]


def expired_packages(conn, store, cutoff):
    return list(conn.scalars(select(packages.c.package_id).where(repo.scope(packages, store), packages.c.exported_at.is_not(None),
        packages.c.exported_at < cutoff).order_by(packages.c.exported_at, packages.c.package_id)))


def prune(conn, store, ids, cutoff):
    conn.execute(update(packages).where(repo.scope(packages, store), packages.c.exported_at.is_not(None),
        packages.c.send_state.in_(("sent", "rejected")), packages.c.payload_json != b"").values(payload_json=b""))
    if ids:
        conn.execute(delete(packages).where(repo.scope(packages, store), packages.c.package_id.in_(ids),
            packages.c.exported_at.is_not(None), packages.c.exported_at < cutoff))
    unexported = exists(select(1).where(packages.c.store_id == counters.c.store_id, packages.c.exported_at.is_(None),
        func.substr(packages.c.period_start, 1, 10) == counters.c.period_start))
    conn.execute(delete(counters).where(repo.scope(counters, store), counters.c.period_start < cutoff[:10],
        counters.c.value == counters.c.packaged_value, ~unexported))
