"""Private route records and remote attempt handles stay Profile-scoped and exact."""

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from gateway import hosted_rooms as native
from gateway.hosted_rooms_common import clock
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.rooms import links, remote_runs, REMOTE_IDENTITY, owed_revokes


def list_room_link_records(store):
    with store.read() as conn:
        return [repo.record(row) for row in conn.execute(select(links).where(repo.scope(links, store))
            .order_by(links.c.room_id, links.c.member_id)).mappings()]


def upsert_room_link_record(store, *, record, max_links, expiry=None):
    fields = {name: record[name] for name in native._LINK_COLUMNS}
    identity = {name: record[name] for name in ("room_id", "member_id")}
    with store.write() as conn:
        repo.lock_store(conn, store)
        existing = conn.execute(select(links).where(repo.key(links, store, identity))).mappings().one_or_none()
        if existing is None and conn.scalar(select(func.count()).select_from(links).where(repo.scope(links, store))) >= max_links:
            raise native.HostedRoomError("too many stored room links")
        if existing is not None and expiry is not None:
            old = repo.record(existing)
            if old['grant'] != record['grant'] and expiry(old['grant']) > expiry(record['grant']):
                from hermes_db.domains.rooms.postgres.operations.revoke_debts import owe_locked
                owe_locked(conn, store, **identity, target_url=old['target_url'], grant=old['grant'],
                    expires_at=expiry(old['grant']), now=clock(None), held=True)
        statement = insert(links).values(store_id=store.scope.require_store_id(), **repo.values(links, fields))
        conn.execute(statement.on_conflict_do_update(index_elements=[links.c.store_id, links.c.room_id, links.c.member_id],
            set_={name: statement.excluded[name] for name in fields if name not in identity}))
        conn.execute(delete(owed_revokes).where(repo.key(owed_revokes, store,
            dict(identity, grant_digest=native.grant_digest(record['grant']))), owed_revokes.c.held == 1))


def update_room_link_status(store, *, room_id, member_id, status, now=None):
    with store.write() as conn:
        repo.lock_store(conn, store)
        return conn.execute(update(links).where(repo.key(links, store, dict(room_id=room_id, member_id=member_id)))
            .values(**repo.values(links, dict(status=status, updated_at=clock(now))))).rowcount == 1


def delete_room_link_records(store, *, room_id):
    with store.write() as conn:
        repo.lock_store(conn, store)
        return conn.execute(delete(links).where(repo.scope(links, store, room_id))).rowcount


def upsert_remote_run_receipt(store, *, record, now=None):
    timestamp = clock(now)
    identity = {name: record[name] for name in REMOTE_IDENTITY}
    with store.write() as conn:
        repo.lock_store(conn, store)
        existing = conn.execute(select(remote_runs).where(repo.key(remote_runs, store, identity))).mappings().one_or_none()
        if existing is not None:
            existing = repo.record(existing)
            if any(existing[name] != record[name] for name in (*REMOTE_IDENTITY, "run_id", "session_id")):
                raise native.HostedRoomError("remote run receipt conflicts with its logical task")
            conn.execute(update(remote_runs).where(repo.key(remote_runs, store, identity)).values(updated_at=timestamp))
            return
        repo.insert_row(conn, store, remote_runs, dict(identity, run_id=record["run_id"], session_id=record["session_id"],
                                                     created_at=timestamp, updated_at=timestamp))
        from hermes_db.domains.rooms.postgres.operations.work import capture_transition_locked
        capture_transition_locked(conn, store, record["room_id"])


def list_remote_run_receipts(store, *, room_id=None, target_profile=None, session_id=None):
    filters = {name: value for name, value in dict(room_id=room_id, target_profile=target_profile, session_id=session_id).items()
               if value is not None}
    with store.read() as conn:
        return [repo.record(row) for row in conn.execute(select(remote_runs).where(repo.key(remote_runs, store, filters))
            .order_by(remote_runs.c.created_at, remote_runs.c.task_id, remote_runs.c.execution_generation)).mappings()]


def remote_run_receipt(store, *, record):
    with store.read() as conn:
        row = conn.execute(select(remote_runs).where(repo.key(remote_runs, store,
            {name: record[name] for name in REMOTE_IDENTITY}))).mappings().one_or_none()
        return repo.record(row) if row is not None else None


def drop_remote_run_receipt(store, *, record, run_id):
    identity = {name: record[name] for name in REMOTE_IDENTITY}
    identity['run_id'] = run_id
    with store.write() as conn:
        repo.lock_store(conn, store)
        deleted = conn.execute(delete(remote_runs).where(repo.key(remote_runs, store, identity))).rowcount == 1
        if deleted:
            from hermes_db.domains.rooms.postgres.operations.work import capture_transition_locked
            capture_transition_locked(conn, store, record['room_id'])
        return deleted
