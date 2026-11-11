"""Portable plugin records: exact namespace/CAS/quota SQL and the selected protocol implementation."""
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.plugins import namespaces, records
from plugins import plugin_storage_types as contract

def scope(table, reference):
    return and_(table.c.store_id == reference.store_id, table.c.plugin_id == reference.plugin_id, table.c.namespace == reference.namespace)

def now(conn):
    return float(conn.scalar(select(func.extract('epoch', func.clock_timestamp()))))

def live(stamp):
    return or_(records.c.expires_at.is_(None), records.c.expires_at > stamp)

def lock_namespace(conn, reference):
    conn.execute(insert(namespaces).values(store_id=reference.store_id, plugin_id=reference.plugin_id, namespace=reference.namespace).on_conflict_do_nothing())
    return conn.scalar(select(namespaces.c.revision).where(scope(namespaces, reference)).with_for_update())

def get(conn, reference, key):
    return contract.decode_record(conn.execute(select(records).where(scope(records, reference), records.c.key == key, live(now(conn)))).mappings().one_or_none())

def put(conn, reference, key, value, expected, ttl):
    revision = lock_namespace(conn, reference) + 1
    stamp = now(conn)
    conn.execute(delete(records).where(scope(records, reference), records.c.expires_at <= stamp))
    row = conn.execute(select(records).where(scope(records, reference), records.c.key == key)).mappings().one_or_none()
    contract.check_revision(row, expected)
    count, size = conn.execute(select(func.count(), func.coalesce(func.sum(func.octet_length(records.c.value)), 0)).where(scope(records, reference))).one()
    if count + (row is None) > contract.MAX_NAMESPACE_KEYS or size - (len(row['value']) if row else 0) + len(value) > contract.MAX_NAMESPACE_BYTES:
        raise contract.PluginStorageQuotaError('Plugin namespace exceeds its retained keys or byte quota')
    expiry = None if ttl is None else stamp + ttl
    stmt = insert(records).values(store_id=reference.store_id, plugin_id=reference.plugin_id, namespace=reference.namespace, key=key, value=value, revision=revision, expires_at=expiry)
    conn.execute(stmt.on_conflict_do_update(index_elements=list(records.primary_key.columns), set_={'value': value, 'revision': revision, 'expires_at': expiry}))
    conn.execute(update(namespaces).where(scope(namespaces, reference)).values(revision=revision))
    return contract.decode_record(dict(key=key, value=value, revision=revision, expires_at=expiry))

def remove(conn, reference, key, expected):
    lock_namespace(conn, reference)
    stamp = now(conn)
    row = conn.execute(select(records).where(scope(records, reference), records.c.key == key, live(stamp))).mappings().one_or_none()
    contract.check_revision(row, expected)
    if row is None:
        return False
    conn.execute(delete(records).where(scope(records, reference), records.c.key == key))
    return True

def scan(conn, reference, after, prefix, limit):
    stmt = select(records).where(scope(records, reference), live(now(conn)))
    if after is not None:
        stmt = stmt.where(records.c.key > after)
    if prefix:
        stmt = stmt.where(func.substr(records.c.key, 1, len(prefix)) == prefix)
    return [contract.decode_record(row) for row in conn.execute(stmt.order_by(records.c.key).limit(limit)).mappings()]

def prune(conn, reference, limit):
    lock_namespace(conn, reference)
    keys = list(conn.scalars(select(records.c.key).where(scope(records, reference), records.c.expires_at <= now(conn)).order_by(records.c.key).limit(limit)))
    return 0 if not keys else conn.execute(delete(records).where(scope(records, reference), records.c.key.in_(keys))).rowcount
