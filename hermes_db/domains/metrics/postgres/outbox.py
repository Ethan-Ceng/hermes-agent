"""Consent windows, package watermarks and exact send-claim settlement; HTTP and file I/O stay outside."""
import uuid
from datetime import timedelta, datetime, UTC
from sqlalchemy import case, exists, select, update, delete, func, or_
from hermes_db.domains.metrics.postgres import records as repo
from hermes_db.tables.metrics import marks, windows, packages, counters, RESOURCE, COUNTER_KEY
import json

def reconcile(conn, store, enabled, now):
    from hermes_cli.observability.shared_metrics import _isoformat
    from hermes_cli.observability.shared_metrics_sender import MAX_OBS_ADVANCE_SECONDS, _parse_stamp
    raw = stamp = _isoformat(now)
    previous = conn.scalar(select(marks.c.stamp).where(repo.key(marks, store, {'name': 'obs'})))
    if previous is not None:
        stamp = min(stamp, _isoformat(_parse_stamp(previous) + timedelta(seconds=MAX_OBS_ADVANCE_SECONDS)))
    repo.advance_mark(conn, store, 'obs', stamp)
    current = dict(conn.execute(select(marks.c.name, marks.c.stamp).where(repo.scope(marks, store))).all())
    row = conn.execute(select(windows).where(repo.scope(windows, store), windows.c.closed_at.is_(None))).mappings().one_or_none()
    if enabled and row is None:
        opened = max(value for value in (current['obs'], current.get('data')) if value is not None)
        conn.execute(windows.insert().values(store_id=store.scope.require_store_id(), window_id=str(uuid.uuid4()), opened_at=opened, last_confirmed_at=opened))
    elif row is not None:
        fields = {'last_confirmed_at': max(row['last_confirmed_at'], current['obs'])} if enabled else {'closed_at': min(row['last_confirmed_at'], raw)}
        conn.execute(update(windows).where(repo.key(windows, store, {'window_id': row['window_id']})).values(**fields))

def gate():
    return exists(select(1).where(windows.c.store_id == packages.c.store_id, packages.c.period_start >= windows.c.opened_at, packages.c.period_end <= case((windows.c.closed_at.is_(None), windows.c.last_confirmed_at), else_=windows.c.closed_at)))

def consented_day(conn, store, start):
    return conn.scalar(select(windows.c.window_id).where(repo.scope(windows, store), windows.c.closed_at.is_(None), windows.c.opened_at <= start).limit(1)) is not None

def create_one(conn, store, now):
    from hermes_cli.observability.shared_metrics import SharedMetricsStore, _compact_json, _isoformat, _PACKAGE_SCHEMA_VERSION
    from hermes_cli.observability.shared_metrics_contract import client_resource_is_valid
    while True:
        first = conn.execute(select(counters).where(repo.scope(counters, store), counters.c.value > counters.c.packaged_value).order_by(counters.c.period_start, *(counters.c[name] for name in RESOURCE)).limit(1)).mappings().one_or_none()
        if first is None or not first['period_start']:
            return None
        group = {name: repo.decode_record(first)[name] for name in ('period_start', *RESOURCE)}
        rows = [repo.decode_record(row) for row in conn.execute(select(counters).where(repo.key(counters, store, group), counters.c.value > counters.c.packaged_value).order_by(counters.c.metric_name, counters.c.dimensions_json)).mappings()]
        resource = {name: group[name] for name in RESOURCE}
        if not client_resource_is_valid(resource):
            raise ValueError('Unsupported shared-metrics client resource')
        metrics = SharedMetricsStore._package_metrics(rows)
        if not metrics:
            mark_packaged(conn, store, rows)
            continue
        start = datetime.fromisoformat(group['period_start']).replace(tzinfo=UTC)
        payload = dict(schema_version=_PACKAGE_SCHEMA_VERSION, package_id=str(uuid.uuid4()), install_id=repo.install_id(conn, store), period_start=_isoformat(start), period_end=_isoformat(start + timedelta(days=1)), generated_at=_isoformat(now), resource=resource, metrics=metrics)
        conn.execute(packages.insert().values(store_id=store.scope.require_store_id(), **repo.values(packages, dict(package_id=payload['package_id'], period_start=payload['period_start'], period_end=payload['period_end'], payload_json=_compact_json(payload), created_at=payload['generated_at']))))
        repo.advance_mark(conn, store, 'data', payload['period_end'])
        mark_packaged(conn, store, rows)
        return payload

def mark_packaged(conn, store, rows):
    for row in rows:
        conn.execute(update(counters).where(repo.key(counters, store, {name: row[name] for name in COUNTER_KEY})).values(packaged_value=counters.c.value))

def create_pending(conn, store, now, *, due=False):
    if due and conn.scalar(select(packages.c.package_id).where(repo.scope(packages, store), func.substr(packages.c.created_at, 1, 10) >= now.date().isoformat()).limit(1)) is not None:
        return
    while create_one(conn, store, now) is not None:
        pass

def pending_exports(conn, store):
    return [repo.decode_record(row) for row in conn.execute(select(packages.c.package_id, packages.c.payload_json).where(repo.scope(packages, store), packages.c.exported_at.is_(None)).order_by(packages.c.created_at, packages.c.package_id)).mappings()]

def expired_packages(conn, store, cutoff):
    return list(conn.scalars(select(packages.c.package_id).where(repo.scope(packages, store), packages.c.exported_at.is_not(None), packages.c.exported_at < cutoff).order_by(packages.c.exported_at, packages.c.package_id)))

def prune(conn, store, ids, cutoff):
    conn.execute(update(packages).where(repo.scope(packages, store), packages.c.exported_at.is_not(None), packages.c.send_state.in_(('sent', 'rejected')), packages.c.payload_json != b'').values(payload_json=b''))
    if ids:
        conn.execute(delete(packages).where(repo.scope(packages, store), packages.c.package_id.in_(ids), packages.c.exported_at.is_not(None), packages.c.exported_at < cutoff))
    unexported = exists(select(1).where(packages.c.store_id == counters.c.store_id, packages.c.exported_at.is_(None), func.substr(packages.c.period_start, 1, 10) == counters.c.period_start))
    conn.execute(delete(counters).where(repo.scope(counters, store), counters.c.period_start < cutoff[:10], counters.c.value == counters.c.packaged_value, ~unexported))

def pending():
    return or_(packages.c.send_state.is_(None), packages.c.send_state == 'pending')

def freeze_identity(conn, store, row):
    try:
        payload = json.loads(row['payload_json'])
    except (TypeError, ValueError):
        reason, identity = ('unreadable payload', None)
    else:
        identity = payload.get('install_id') if isinstance(payload, dict) else None
        reason = None if isinstance(identity, str) and identity.strip() else 'payload has no usable install_id'
    if reason is not None:
        repo.change_package(conn, store, packages, row['package_id'], dict(send_state='rejected', last_error=reason))
        return None
    repo.change_package(conn, store, packages, row['package_id'], dict(sent_install_id=identity))
    return identity

def claim(conn, store, now, seen):
    from hermes_cli.observability.shared_metrics import _isoformat
    from hermes_cli.observability.shared_metrics_sender import MAX_SEND_ATTEMPTS, _CLAIM_LEASE_SECONDS
    stmt = select(packages).where(repo.scope(packages, store), packages.c.exported_at.is_not(None), pending(), or_(packages.c.next_attempt_at.is_(None), packages.c.next_attempt_at <= _isoformat(now)), gate(), packages.c.send_attempts < MAX_SEND_ATTEMPTS)
    if seen:
        stmt = stmt.where(packages.c.package_id.not_in(sorted(seen)))
    row = conn.execute(stmt.order_by(packages.c.created_at, packages.c.package_id).limit(1).with_for_update()).mappings().one_or_none()
    if row is None:
        return None
    row = repo.decode_record(row)
    identity = row['sent_install_id'] or freeze_identity(conn, store, row)
    if identity is None:
        return dict(package_id=row['package_id'], skip=True)
    token = str(uuid.uuid4())
    repo.change_package(conn, store, packages, row['package_id'], dict(send_state='pending', send_attempts=row['send_attempts'] + 1, next_attempt_at=_isoformat(now + timedelta(seconds=_CLAIM_LEASE_SECONDS)), claim_token=token))
    return dict(package_id=row['package_id'], payload_json=row['payload_json'], derived=identity, claim_token=token, skip=False)

def mark(conn, store, package_id, token, columns):
    allowed = {'send_state', 'sent_at', 'last_error', 'next_attempt_at'}
    if not columns.keys() <= allowed:
        raise ValueError('Unsupported send settlement columns')
    conditions = [pending()]
    if token is not None:
        conditions.append(packages.c.claim_token == token)
    return repo.change_package(conn, store, packages, package_id, columns, *conditions)

def renew(conn, store, package_id, token, now):
    from hermes_cli.observability.shared_metrics import _isoformat
    from hermes_cli.observability.shared_metrics_sender import _CLAIM_LEASE_SECONDS
    if token is None:
        return False
    return repo.change_package(conn, store, packages, package_id, dict(next_attempt_at=_isoformat(now + timedelta(seconds=_CLAIM_LEASE_SECONDS))), pending(), packages.c.claim_token == token, packages.c.next_attempt_at > _isoformat(now)) == 1
