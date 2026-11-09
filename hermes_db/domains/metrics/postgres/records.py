"""Metric record encoding, counters and latches on the caller Connection and owning scope."""
import uuid
from sqlalchemy import LargeBinary, and_, select, update, func
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.metrics import locks, state, counters, marks
from hermes_db.core.values import encode_text, decode_text
import json
from datetime import timedelta

def scope(table, store):
    return table.c.store_id == store.scope.require_store_id()

def values(table, record):
    return {name: encode_text(value) if value is not None and isinstance(table.c[name].type, LargeBinary) else value for name, value in record.items()}

def decode_record(row):
    return {name: decode_text(value) if isinstance(value, (bytes, memoryview)) else value for name, value in row.items() if name != 'store_id'}

def key(table, store, fields):
    return and_(scope(table, store), *(table.c[name] == value for name, value in values(table, fields).items()))

def lock_store(conn, store):
    conn.execute(insert(locks).values(store_id=store.scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks).where(scope(locks, store)).with_for_update()).one()

def get_state(conn, store, name):
    value = conn.scalar(select(state.c.value).where(key(state, store, {'key': name})))
    return None if value is None else decode_text(value)

def set_state(conn, store, name, value):
    stmt = insert(state).values(store_id=store.scope.require_store_id(), **values(state, {'key': name, 'value': value}))
    conn.execute(stmt.on_conflict_do_update(index_elements=[state.c.store_id, state.c.key], set_={'value': stmt.excluded.value}))

def install_id(conn, store):
    result = get_state(conn, store, 'install_id')
    if result is None:
        result = str(uuid.uuid4())
        set_state(conn, store, 'install_id', result)
    return result

def increment(conn, store, metric, dimensions, resource, period, amount=1):
    from hermes_cli.observability.shared_metrics import _compact_json
    data = dict(period_start=period, metric_name=metric, dimensions_json=_compact_json(dimensions), **resource, value=amount, packaged_value=0)
    stmt = insert(counters).values(store_id=store.scope.require_store_id(), **values(counters, data))
    conn.execute(stmt.on_conflict_do_update(index_elements=list(counters.primary_key.columns), set_={'value': counters.c.value + stmt.excluded.value}))

def advance_mark(conn, store, name, stamp):
    stmt = insert(marks).values(store_id=store.scope.require_store_id(), name=name, stamp=stamp)
    conn.execute(stmt.on_conflict_do_update(index_elements=[marks.c.store_id, marks.c.name], set_={'stamp': func.greatest(marks.c.stamp, stmt.excluded.stamp)}))

def change_package(conn, store, table, package_id, changes, *conditions):
    return conn.execute(update(table).where(key(table, store, {'package_id': package_id}), *conditions).values(**values(table, changes))).rowcount

def record(conn, store, metric, dimensions, resource, now, amount=1):
    install_id(conn, store)
    increment(conn, store, metric, dimensions, resource, now.date().isoformat(), amount)

def once(conn, store, state_key, metric, dimensions, resource, now, *, interval=False, daily=False):
    from hermes_cli.observability.shared_metrics import SharedMetricsStore, _isoformat
    previous = get_state(conn, store, state_key)
    if interval:
        stamp = SharedMetricsStore._parse_state_timestamp(previous)
        if stamp is not None and stamp > now:
            set_state(conn, store, state_key, _isoformat(now))
            return False
        if stamp is not None and now < stamp + timedelta(hours=24):
            return False
    elif previous is not None and (not daily or previous == now.date().isoformat()):
        return False
    record(conn, store, metric, dimensions, resource, now)
    set_state(conn, store, state_key, now.date().isoformat() if daily else _isoformat(now))
    return True

def latched(conn, store, prefix):
    rows = conn.scalars(select(state.c.key).where(scope(state, store)))
    return frozenset(name[len(prefix):] for raw in rows if (name := decode_text(raw)).startswith(prefix))

def rollup(conn, store, state_key, update):
    from hermes_cli.observability.shared_metrics import _compact_json
    from hermes_cli.observability.shared_metrics_contract import counter_dimensions_are_valid, client_resource_is_valid
    raw = get_state(conn, store, state_key)
    try:
        previous = json.loads(raw) if raw is not None else None
    except (TypeError, ValueError):
        previous = None
    new_state, rows = update(previous if isinstance(previous, dict) else None)
    for metric, dimensions, resource, period in rows:
        if counter_dimensions_are_valid(metric, dimensions) and client_resource_is_valid(resource):
            install_id(conn, store)
            increment(conn, store, metric, dimensions, resource, period)
    set_state(conn, store, state_key, _compact_json(new_state))

def snapshot(conn, store):
    rows = conn.execute(select(counters).where(scope(counters, store)).order_by(*(counters.c[name] for name in ('period_start', 'hermes_version', 'os_family', 'architecture', 'install_method', 'metric_name', 'dimensions_json')))).mappings()
    return [dict(period_start=row['period_start'], metric_name=row['metric_name'], resource={name: row[name] for name in ('hermes_version', 'os_family', 'architecture', 'install_method')}, dimensions=json.loads(row['dimensions_json']), value=row['value'], packaged_value=row['packaged_value']) for raw in rows if (row := decode_record(raw))]
