"""Bound and scoped Discord statements; opaque SDK ids are stored losslessly."""

from sqlalchemy import LargeBinary, and_, select
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.discord_recovery import locks, messages
from hermes_db.core.values import encode_text, decode_text


def scope(table, reference):
    return and_(table.c.store_id == reference.store_id, table.c.plugin_id == reference.plugin_id)


def values(table, record):
    return {name: encode_text(value) if value is not None and isinstance(table.c[name].type, LargeBinary) else value for name, value in record.items()}


def identity(table, reference, message_id):
    return and_(scope(table, reference), table.c.message_id == encode_text(message_id))


def record(row):
    return None if row is None else {name: decode_text(value) if isinstance(value, (bytes, memoryview)) else value for name, value in row.items()}


def lock_store(conn, reference):
    conn.execute(insert(locks).values(store_id=reference.store_id, plugin_id=reference.plugin_id).on_conflict_do_nothing())
    conn.execute(select(locks).where(scope(locks, reference)).with_for_update()).one()


def message(conn, reference, message_id):
    return record(conn.execute(select(messages).where(identity(messages, reference, message_id))).mappings().one_or_none())


def insert_row(conn, reference, table, row):
    conn.execute(table.insert().values(store_id=reference.store_id, plugin_id=reference.plugin_id, **values(table, row)))
