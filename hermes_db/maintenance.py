"""Named business maintenance on the caller's selected Connection and scope."""


def prune_plugin_records(conn, scope, limit=200):
    from sqlalchemy import delete, func, select, tuple_
    from hermes_db.tables.plugins import records
    expired = (records.c.store_id == scope.require_store_id()) & (records.c.expires_at <= func.extract("epoch", func.clock_timestamp()))
    keys = select(records.c.plugin_id, records.c.namespace, records.c.key).where(expired).limit(limit)
    return conn.execute(delete(records).where(expired,
        tuple_(records.c.plugin_id, records.c.namespace, records.c.key).in_(keys))).rowcount


def attachment_namespace(conn, scope):
    from sqlalchemy import select
    from hermes_db.tables.room_attachments import roots
    return conn.scalar(select(roots.c.namespace).where(roots.c.store_id == scope.require_store_id()))
