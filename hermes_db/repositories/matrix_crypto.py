"""Core statements always bind Profile/account/device; values never normalize SDK text."""

import uuid
from sqlalchemy import LargeBinary, and_, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.matrix_crypto import resource_for
from hermes_db.errors import StorageConfigurationError
from hermes_db.tables.matrix_crypto import roots
from hermes_db.core.values import encode_text, decode_text

RAW_FIELDS = frozenset({"pickle", "account_pickle"})


def scope(table, reference):
    return and_(table.c.store_id == reference.store_id, table.c.account_key == encode_text(reference.account_key), table.c.owner_device == encode_text(reference.owner_device))


def values(table, record):
    return {name: encode_text(value) if isinstance(value, str) and isinstance(table.c[name].type, LargeBinary) else value for name, value in record.items()}


def decode(row):
    return None if row is None else {name: (bytes(value) if name in RAW_FIELDS else decode_text(value)) if isinstance(value, (bytes, memoryview)) else value for name, value in row.items()}


def key(table, reference, fields):
    return and_(scope(table, reference), *(table.c[name] == value for name, value in values(table, fields).items()))


def row(conn, reference, table, fields=None):
    return decode(conn.execute(select(table).where(key(table, reference, fields or {}))).mappings().one_or_none())


def upsert(conn, reference, table, record, *, preserve=()):
    stmt = insert(table).values(store_id=reference.store_id, account_key=encode_text(reference.account_key), owner_device=encode_text(reference.owner_device), **values(table, record))
    updates = {name: getattr(stmt.excluded, name) for name in record if name not in preserve and not table.c[name].primary_key}
    conn.execute(stmt.on_conflict_do_update(index_elements=list(table.primary_key.columns), set_=updates) if updates else stmt.on_conflict_do_nothing())


def change(conn, reference, table, fields, record):
    return conn.execute(update(table).where(key(table, reference, fields)).values(**values(table, record))).rowcount


def initialize(reference):
    with resource_for(reference) as resource, resource.write() as conn:
        conn.execute(insert(roots).values(store_id=reference.store_id, account_key=encode_text(reference.account_key), owner_device=encode_text(reference.owner_device),
            generation=uuid.uuid4().hex, device_id=encode_text(reference.owner_device)).on_conflict_do_nothing())
        return conn.scalar(select(roots.c.generation).where(scope(roots, reference)))


def check_generation(conn, reference, *, lock=False):
    stmt = select(roots.c.generation).where(scope(roots, reference))
    current = conn.scalar(stmt.with_for_update() if lock else stmt)
    if current is None or current != reference.generation:
        raise StorageConfigurationError("Captured Matrix encryption dataset changed; reopen its owning adapter")
