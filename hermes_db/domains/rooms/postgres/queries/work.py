"""Scoped passive evidence, exact retained-byte accounting and immutable revisions."""

from sqlalchemy import cast, func, LargeBinary, select, Text, update
from gateway import hosted_room_work_records as native, hosted_room_work_storage as storage
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.tables.room_work import source, pending, publications


def unpublished(table, store):
    def comparable(column, target):
        return func.convert_to(column, "UTF8") if isinstance(target.type, LargeBinary) and not isinstance(column.type, LargeBinary) else column
    return ~select(publications.c.task_id).where(room_repo.scope(publications, store),
        comparable(publications.c.room_id, table.c.room_id) == table.c.room_id,
        comparable(publications.c.task_id, table.c.task_id) == comparable(table.c.task_id, publications.c.task_id),
        publications.c.kind.in_(("turn.settled", "turn.failed", "turn.cancelled"))).exists()


def record_key(table, store, record, target=None):
    fields = dict(room_id=record["room_id"], producer_gateway_id=record["authority"]["gateway_id"],
                  producer_epoch=record["authority"]["epoch"])
    if target is not None:
        fields["target_install_id"] = target
    return room_repo.key(table, store, fields)


def read(conn, store, table, condition):
    row = conn.execute(select(table).where(room_repo.scope(table, store), condition).with_for_update()).mappings().one_or_none()
    return room_repo.record(row) if row is not None else None


def validate_locked(conn, store, table, row):
    try:
        return storage.validate_stored(row)
    except native.InvalidStoredWorkRecord:
        if row["disposition"] == "current":
            conn.execute(update(table).where(room_repo.key(table, store, row)).values(disposition="invalid"))
        raise


def _size(table):
    fields = storage.retained_fields(table.name)
    return 20 + sum(func.coalesce(func.octet_length(
        table.c[field] if field == "record_json" else func.convert_to(cast(table.c[field], Text), "UTF8")), 0) for field in fields)


def _budget(conn, store, table, row, previous):
    total = count = 0
    for retained in (source, pending):
        size, rows = conn.execute(select(func.coalesce(func.sum(_size(retained)), 0), func.count()).select_from(
            retained).where(room_repo.scope(retained, store))).one()
        total += int(size)
        count += rows
    def size_of(value):
        return 20 + sum(len(str(value[field]).encode("utf-8")) for field in storage.retained_fields(table.name)
                        if value.get(field) is not None)
    old_size = size_of(previous) if previous else 0
    if total - old_size + size_of(row) > native.MAX_STORE_BYTES or count - bool(previous) + 1 > native.MAX_STORE_ROWS:
        raise native.WorkRecordCapacityError("work record storage is full")


def save(conn, store, table, record, *, target_install_id=None, route_generation=None):
    row = dict(room_id=record["room_id"], producer_gateway_id=record["authority"]["gateway_id"],
        producer_epoch=record["authority"]["epoch"], revision=record["revision"], digest=record["digest"],
        record_json=native.encode(record), disposition="current")
    if target_install_id is not None:
        row.update(target_install_id=target_install_id, route_generation=route_generation, status="pending")
    condition = record_key(table, store, record, target_install_id)
    previous = read(conn, store, table, condition)
    if previous is not None and previous["disposition"] != "current":
        raise native.WorkRecordError("historical work record is immutable")
    _budget(conn, store, table, row, previous)
    if previous is None:
        room_repo.insert_row(conn, store, table, row)
    else:
        conn.execute(update(table).where(condition).values(**room_repo.values(table, row)))
