"""Member/attempt home evidence on the owning store's Core transaction."""

import json
from pathlib import Path
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from gateway import session_hosted_member_homes as native
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo
from hermes_db.tables.runtime import state_meta
from hermes_db.tables.room_runs import tasks


def _key(db, key):
    return (state_meta.c.store_id == db.scope.require_store_id()) & (state_meta.c.key == key)


def recorded_homes(db, room_id, member_id):
    with db._read() as conn:
        value = conn.scalar(select(state_meta.c.value).where(_key(db, native._key(room_id, member_id))))
    return [Path(home) for home in json.loads(value)] if value is not None else []


def record_member_home(db, room_id, member_id, home):
    home, key = str(home), native._key(room_id, member_id)
    if Path(home) in recorded_homes(db, room_id, member_id):
        return
    with db._write() as conn:
        room_repo.lock_store(conn, db)
        value = conn.scalar(select(state_meta.c.value).where(_key(db, key)))
        homes = json.loads(value) if value is not None else []
        if home not in homes:
            stmt = insert(state_meta).values(store_id=db.scope.require_store_id(), key=key, value=json.dumps([*homes, home]))
            conn.execute(stmt.on_conflict_do_update(index_elements=list(state_meta.primary_key.columns), set_={'value': stmt.excluded.value}))


def _attempts(conn, db, room_id, member_id, statuses):
    rows = conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == db.scope.require_store_id(),
        state_meta.c.key.startswith(native._attempt_prefix(room_id, member_id), autoescape=True))).all()
    ids = {json.loads(key[len(native._HOMES):])[2] for key, _ in rows}
    current = {row['task_id']: row for row in conn.execute(select(tasks.c.task_id, tasks.c.status, tasks.c.execution_generation)
        .where(room_repo.scope(tasks, db, room_id), tasks.c.task_id.in_(ids))).mappings()}
    found = {}
    for key, home in rows:
        task_id, generation = json.loads(key[len(native._HOMES):])[2:]
        row = current.get(task_id)
        found[key] = home, bool(row and row['status'] in statuses and row['execution_generation'] == generation)
    return found


def record_attempt_home(db, room_id, member_id, task_id, generation, home):
    key = native._HOMES + json.dumps([room_id, member_id, task_id, int(generation)], separators=(',', ':'))
    with db._write() as conn:
        room_repo.lock_store(conn, db)
        for old, (_, live) in _attempts(conn, db, room_id, member_id, native._LIVE_ATTEMPT).items():
            if not live and old != key:
                conn.execute(delete(state_meta).where(_key(db, old)))
        conn.execute(insert(state_meta).values(store_id=db.scope.require_store_id(), key=key, value=str(home)).on_conflict_do_nothing())


def stopping_attempt_home(db, room_id, member_id, task):
    if task.get('status') not in native._STOPPING:
        return None
    key = native._HOMES + json.dumps([room_id, member_id, task['identity'].task_id, int(task['execution_generation'])], separators=(',', ':'))
    with db._read() as conn:
        value = conn.scalar(select(state_meta.c.value).where(_key(db, key)))
    return Path(value) if value is not None else None


def stopping_attempt_homes(db, room_id, member_id):
    with db._read() as conn:
        return {home for home, live in _attempts(conn, db, room_id, member_id, native._STOPPING).values() if live}


def forget_locked(conn, store, room_id):
    prefix = native._HOMES + json.dumps([room_id], separators=(',', ':'))[:-1] + ','
    conn.execute(delete(state_meta).where(state_meta.c.store_id == store.scope.require_store_id(),
        state_meta.c.key.startswith(prefix, autoescape=True)))
