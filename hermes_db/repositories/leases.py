"""Lease row primitives on a connection already holding the lineage root lock."""

from sqlalchemy import select


def where(scope, table, key_column, key):
    return (table.c.store_id == scope.require_store_id(), table.c[key_column] == key)


def claim(conn, scope, table, key_column, key, holder, now, expires_at):
    conditions = where(scope, table, key_column, key)
    row = conn.execute(select(table).where(*conditions).with_for_update()).mappings().one_or_none()
    reclaimed = None
    if row is not None and row["expires_at"] <= now:
        conn.execute(table.delete().where(*conditions, table.c.holder == row["holder"]))
        reclaimed = row["holder"]
        row = None
    if row is None:
        conn.execute(table.insert().values(store_id=scope.require_store_id(), **{key_column: key},
            holder=holder, acquired_at=now, expires_at=expires_at))
        return True, reclaimed
    return row["holder"] == holder, reclaimed


def renew(conn, scope, table, key_column, key, holder, expires_at):
    return conn.execute(table.update().where(*where(scope, table, key_column, key), table.c.holder == holder)
                         .values(expires_at=expires_at)).rowcount > 0


def release(conn, scope, table, key_column, key, holder):
    return conn.execute(table.delete().where(*where(scope, table, key_column, key), table.c.holder == holder)).rowcount


def merge_turn_roots(conn, scope, old_root, new_root, now):
    """Move an existing lease with a constructor backfill, under both root locks."""
    from hermes_db.errors import StorageConflictError
    from hermes_db.tables.gateway import session_turn_leases as table

    if old_root == new_root:
        return
    rows = {row["conversation_id"]: dict(row) for row in conn.execute(select(table).where(
        table.c.store_id == scope.require_store_id(), table.c.conversation_id.in_((old_root, new_root)))
        .with_for_update()).mappings()}
    old, target = rows.get(old_root), rows.get(new_root)
    if old is None:
        return
    if target and old["holder"] != target["holder"] and min(old["expires_at"], target["expires_at"]) > now:
        raise StorageConflictError("Cannot join conversation roots owned by different live turn holders")
    winner = max(rows.values(), key=lambda row: row["expires_at"])
    if target and old["holder"] == target["holder"]:
        winner = dict(winner, acquired_at=min(old["acquired_at"], target["acquired_at"]))
    conn.execute(table.delete().where(table.c.store_id == scope.require_store_id(),
        table.c.conversation_id.in_((old_root, new_root))))
    conn.execute(table.insert().values(**dict(winner, conversation_id=new_root)))
