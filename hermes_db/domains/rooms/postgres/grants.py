"""Room grants workflow; original connection, fence and off-connection effect boundaries are preserved."""
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.rooms import rules as native
from hermes_db.domains.rooms.rules import clock, bounded_grant_expiry
from hermes_db.domains.rooms.postgres import repository as repo
from hermes_db.tables.rooms import reservations, revoked_grants, links, remote_runs, REMOTE_IDENTITY, owed_revokes, owed_revokes as debts

def revoke_room_grant_scope(store, *, claims, expires_at, now=None):
    key, timestamp, expiry = (native._room_grant_scope_key(claims), clock(now), float(expires_at))
    if expiry <= timestamp:
        return
    with store.write() as conn:
        repo.lock_store(conn, store)
        conn.execute(delete(revoked_grants).where(repo.scope(revoked_grants, store), revoked_grants.c.expires_at <= timestamp))
        statement = insert(revoked_grants).values(store_id=store.scope.require_store_id(), scope_key=key, expires_at=expiry, revoked_before=timestamp)
        conn.execute(statement.on_conflict_do_update(index_elements=[revoked_grants.c.store_id, revoked_grants.c.scope_key], set_={'expires_at': func.greatest(revoked_grants.c.expires_at, expiry), 'revoked_before': func.greatest(revoked_grants.c.revoked_before, timestamp)}))
        fields = native._claim_values(claims, ('room_id', 'member_id', 'target_profile', 'authority_gateway_id'))
        fields['authority_epoch'] = int(claims.get('authority_epoch') or 0)
        conn.execute(update(reservations).where(repo.key(reservations, store, fields)).values(revoked_at=timestamp, updated_at=timestamp))

def _live(store, room_id, target_profile, timestamp):
    return repo.key(reservations, store, dict(room_id=room_id, target_profile=target_profile)) & (reservations.c.expires_at > timestamp) & reservations.c.revoked_at.is_(None)

def reserve_peer_room(store, *, claims, expires_at, now=None):
    timestamp, expiry = (clock(now), float(expires_at))
    if expiry <= timestamp:
        raise native.HostedRoomError('peer room reservation must expire in the future')
    room_id, member_id, profile, gateway, epoch = native._reservation_claims(claims)
    identity = dict(room_id=room_id, member_id=member_id, target_profile=profile)
    with store.write() as conn:
        repo.lock_store(conn, store)
        conn.execute(delete(reservations).where(repo.scope(reservations, store), reservations.c.expires_at <= timestamp))
        live = list(conn.execute(select(reservations).where(_live(store, room_id, profile, timestamp))).mappings())
        existing = conn.execute(select(reservations).where(repo.key(reservations, store, identity))).mappings().one_or_none()
        candidates = live + ([existing] if existing is not None else [])
        if any(native._reservation_superseded(repo.decode(row), gateway, epoch) for row in candidates):
            raise native.AuthorityConflictError('peer room reservation authority changed')
        conn.execute(update(reservations).where(repo.key(reservations, store, dict(room_id=room_id, target_profile=profile)), reservations.c.authority_epoch < epoch, reservations.c.revoked_at.is_(None)).values(revoked_at=timestamp, updated_at=timestamp))
        fields = dict(identity, authority_gateway_id=gateway, authority_epoch=epoch, expires_at=expiry, revoked_at=None, created_at=timestamp, updated_at=timestamp)
        statement = insert(reservations).values(store_id=store.scope.require_store_id(), **repo.values(reservations, fields))
        updates = {name: statement.excluded[name] for name in ('authority_gateway_id', 'authority_epoch', 'revoked_at', 'updated_at')}
        updates['expires_at'] = func.greatest(reservations.c.expires_at, expiry)
        conn.execute(statement.on_conflict_do_update(index_elements=[reservations.c.store_id, reservations.c.room_id, reservations.c.member_id, reservations.c.target_profile], set_=updates))

def peer_room_is_reserved(store, *, room_id, target_profile, now=None):
    room_id, profile = (native._room_id(room_id), native._actor_id(target_profile, 'target_profile'))
    with store.read() as conn:
        return conn.scalar(select(reservations.c.room_id).where(_live(store, room_id, profile, clock(now))).limit(1)) is not None

def probe_peer_room_reservation(store, *, room_id, target_profile, now=None):
    return peer_room_is_reserved(store, room_id=room_id, target_profile=target_profile, now=now)

def peer_room_grant_is_current(store, *, claims, now=None):
    fields = dict(zip(('room_id', 'member_id', 'target_profile', 'authority_gateway_id', 'authority_epoch'), native._reservation_claims(claims), strict=True))
    with store.read() as conn:
        return conn.scalar(select(reservations.c.room_id).where(repo.key(reservations, store, fields), reservations.c.expires_at > clock(now), reservations.c.revoked_at.is_(None))) is not None

def room_grant_is_revoked(store, *, claims, now=None):
    key = native._room_grant_scope_key(claims)
    with store.read() as conn:
        revoked = conn.scalar(select(revoked_grants.c.revoked_before).where(repo.scope(revoked_grants, store), revoked_grants.c.scope_key == key, revoked_grants.c.expires_at > clock(now)))
        return revoked is not None and float(claims.get('issued_at') or 0) <= revoked

def list_room_link_records(store):
    with store.read() as conn:
        return [repo.record(row) for row in conn.execute(select(links).where(repo.scope(links, store)).order_by(links.c.room_id, links.c.member_id)).mappings()]

def upsert_room_link_record(store, *, record, max_links, expiry=None):
    fields = {name: record[name] for name in native._LINK_COLUMNS}
    identity = {name: record[name] for name in ('room_id', 'member_id')}
    with store.write() as conn:
        repo.lock_store(conn, store)
        existing = conn.execute(select(links).where(repo.key(links, store, identity))).mappings().one_or_none()
        if existing is None and conn.scalar(select(func.count()).select_from(links).where(repo.scope(links, store))) >= max_links:
            raise native.HostedRoomError('too many stored room links')
        if existing is not None and expiry is not None:
            old = repo.record(existing)
            if old['grant'] != record['grant'] and expiry(old['grant']) > expiry(record['grant']):
                from hermes_db.domains.rooms.postgres.grants import owe_locked
                owe_locked(conn, store, **identity, target_url=old['target_url'], grant=old['grant'], expires_at=expiry(old['grant']), now=clock(None), held=True)
        statement = insert(links).values(store_id=store.scope.require_store_id(), **repo.values(links, fields))
        conn.execute(statement.on_conflict_do_update(index_elements=[links.c.store_id, links.c.room_id, links.c.member_id], set_={name: statement.excluded[name] for name in fields if name not in identity}))
        conn.execute(delete(owed_revokes).where(repo.key(owed_revokes, store, dict(identity, grant_digest=native.grant_digest(record['grant']))), owed_revokes.c.held == 1))

def update_room_link_status(store, *, room_id, member_id, status, now=None):
    with store.write() as conn:
        repo.lock_store(conn, store)
        return conn.execute(update(links).where(repo.key(links, store, dict(room_id=room_id, member_id=member_id))).values(**repo.values(links, dict(status=status, updated_at=clock(now))))).rowcount == 1

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
            if any(existing[name] != record[name] for name in (*REMOTE_IDENTITY, 'run_id', 'session_id')):
                raise native.HostedRoomError('remote run receipt conflicts with its logical task')
            conn.execute(update(remote_runs).where(repo.key(remote_runs, store, identity)).values(updated_at=timestamp))
            return
        repo.insert_row(conn, store, remote_runs, dict(identity, run_id=record['run_id'], session_id=record['session_id'], created_at=timestamp, updated_at=timestamp))
        from hermes_db.domains.rooms.postgres.work import capture_transition_locked
        capture_transition_locked(conn, store, record['room_id'])

def list_remote_run_receipts(store, *, room_id=None, target_profile=None, session_id=None):
    filters = {name: value for name, value in dict(room_id=room_id, target_profile=target_profile, session_id=session_id).items() if value is not None}
    with store.read() as conn:
        return [repo.record(row) for row in conn.execute(select(remote_runs).where(repo.key(remote_runs, store, filters)).order_by(remote_runs.c.created_at, remote_runs.c.task_id, remote_runs.c.execution_generation)).mappings()]

def remote_run_receipt(store, *, record):
    with store.read() as conn:
        row = conn.execute(select(remote_runs).where(repo.key(remote_runs, store, {name: record[name] for name in REMOTE_IDENTITY}))).mappings().one_or_none()
        return repo.record(row) if row is not None else None

def drop_remote_run_receipt(store, *, record, run_id):
    identity = {name: record[name] for name in REMOTE_IDENTITY}
    identity['run_id'] = run_id
    with store.write() as conn:
        repo.lock_store(conn, store)
        deleted = conn.execute(delete(remote_runs).where(repo.key(remote_runs, store, identity))).rowcount == 1
        if deleted:
            from hermes_db.domains.rooms.postgres.work import capture_transition_locked
            capture_transition_locked(conn, store, record['room_id'])
        return deleted

def owe_locked(conn, store, *, room_id, member_id, target_url, grant, expires_at, now, held=False):
    expiry = bounded_grant_expiry(expires_at, now=now, horizon=native.MAX_OWED_REVOKE_SECONDS)
    identity = dict(room_id=room_id, member_id=member_id, grant_digest=native.grant_digest(grant))
    if conn.scalar(select(debts.c.grant_digest).where(repo.key(debts, store, identity))) is not None:
        return
    member = repo.key(debts, store, dict(room_id=room_id, member_id=member_id))
    if conn.scalar(select(func.count()).select_from(debts).where(member)) >= native.MAX_OWED_REVOKES_PER_MEMBER:
        if held:
            raise native.HostedRoomError('too many held group chat grant revokes')
        raise native.OwedRevokesFullError('too many owed revokes for this group chat member')
    if conn.scalar(select(func.count()).select_from(debts).where(repo.scope(debts, store))) >= native.MAX_OWED_REVOKES:
        conn.execute(delete(debts).where(repo.scope(debts, store), debts.c.expires_at <= now))
        if conn.scalar(select(func.count()).select_from(debts).where(repo.scope(debts, store))) >= native.MAX_OWED_REVOKES:
            raise native.OwedRevokesFullError('too many owed room grant revokes')
    repo.insert_row(conn, store, debts, dict(identity, target_url=target_url, grant=grant, expires_at=expiry, next_attempt_at=now, created_at=now, held=int(held)))

def room_has_peer_obligations(store, *, room_id, now=None):
    room_id = native._room_id(room_id)
    with store.read() as conn:
        route = conn.scalar(select(links.c.room_id).where(repo.scope(links, store, room_id)).limit(1))
        debt = conn.scalar(select(debts.c.room_id).where(repo.scope(debts, store, room_id), debts.c.expires_at > clock(now)).limit(1))
        return route is not None or debt is not None

def owe_room_grant_revoke(store, *, now=None, **fields):
    with store.write() as conn:
        repo.lock_store(conn, store)
        owe_locked(conn, store, **fields, now=clock(now))

def hold_room_grant_revoke(store, *, room_id, now=None, **fields):
    with store.write() as conn:
        repo.lock_store(conn, store)
        room = repo.room(conn, store, room_id, include_disbanded=True, lock=True)
        try:
            owe_locked(conn, store, room_id=room_id, **fields, now=clock(now), held=room['disbanded_at'] is None)
        except native.OwedRevokesFullError as exc:
            if room['disbanded_at'] is None:
                raise native.HostedRoomError('too many held group chat grant revokes') from exc
            raise

def owes_room_grant_revokes(store):
    with store.read() as conn:
        return conn.scalar(select(debts.c.room_id).where(repo.scope(debts, store)).limit(1)) is not None

def due_room_grant_revokes(store, *, limit, now=None):
    timestamp = clock(now)
    fields = ('room_id', 'member_id', 'grant_digest', 'target_url', 'grant', 'attempts')
    with store.read() as conn:
        rows = [repo.record(row) for row in conn.execute(select(*(debts.c[name] for name in fields)).where(repo.scope(debts, store), debts.c.held == 0, debts.c.next_attempt_at <= timestamp, debts.c.expires_at > timestamp).order_by(debts.c.next_attempt_at, debts.c.created_at).limit(int(limit))).mappings()]
        expired = conn.scalar(select(debts.c.room_id).where(repo.scope(debts, store), debts.c.expires_at <= timestamp).limit(1))
    if expired is not None:
        with store.write() as conn:
            repo.lock_store(conn, store)
            conn.execute(delete(debts).where(repo.scope(debts, store), debts.c.expires_at <= timestamp))
    return rows

def held_room_grant_revokes(store, *, room_id, now=None):
    timestamp = clock(now)
    with store.write() as conn:
        repo.lock_store(conn, store)
        condition = repo.scope(debts, store, room_id) & (debts.c.held == 1)
        conn.execute(delete(debts).where(condition, debts.c.expires_at <= timestamp))
        return [repo.record(row) for row in conn.execute(select(debts.c.target_url, debts.c.grant).where(condition, debts.c.expires_at > timestamp)).mappings()]

def settle_room_grant_revoke(store, *, room_id, member_id, grant_digest, retry_at=None):
    with store.write() as conn:
        repo.lock_store(conn, store)
        condition = repo.key(debts, store, dict(room_id=room_id, member_id=member_id, grant_digest=grant_digest))
        if retry_at is None:
            conn.execute(delete(debts).where(condition))
        else:
            conn.execute(update(debts).where(condition).values(attempts=debts.c.attempts + 1, next_attempt_at=float(retry_at)))

def retire_room_link_records(store, *, room_id, expiry=None, now=None, revoked_digests=None):
    timestamp = clock(now)
    with store.write() as conn:
        repo.lock_store(conn, store)
        rows = [repo.record(row) for row in conn.execute(select(links).where(repo.scope(links, store, room_id))).mappings()]
        if expiry is not None:
            for row in rows:
                owe_locked(conn, store, room_id=room_id, member_id=row['member_id'], target_url=row['target_url'], grant=row['grant'], expires_at=expiry(row['grant']), now=timestamp)
        conn.execute(delete(links).where(repo.scope(links, store, room_id)))
        held = repo.scope(debts, store, room_id) & (debts.c.held == 1)
        if expiry is not None:
            conn.execute(update(debts).where(held).values(held=0, next_attempt_at=timestamp))
        else:
            if revoked_digests is not None:
                held &= debts.c.grant_digest.in_(revoked_digests)
            conn.execute(delete(debts).where(held))
        return len(rows)
