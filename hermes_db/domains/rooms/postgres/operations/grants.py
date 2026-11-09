"""Exact revocation scopes and authority-fenced peer reservations under a store lock."""

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from gateway import hosted_rooms as native
from gateway.hosted_rooms_common import clock
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.rooms import reservations, revoked_grants


def revoke_room_grant_scope(store, *, claims, expires_at, now=None):
    key, timestamp, expiry = native._room_grant_scope_key(claims), clock(now), float(expires_at)
    if expiry <= timestamp:
        return
    with store.write() as conn:
        repo.lock_store(conn, store)
        conn.execute(delete(revoked_grants).where(repo.scope(revoked_grants, store), revoked_grants.c.expires_at <= timestamp))
        statement = insert(revoked_grants).values(store_id=store.scope.require_store_id(), scope_key=key,
                                                expires_at=expiry, revoked_before=timestamp)
        conn.execute(statement.on_conflict_do_update(index_elements=[revoked_grants.c.store_id, revoked_grants.c.scope_key],
            set_={"expires_at": func.greatest(revoked_grants.c.expires_at, expiry),
                  "revoked_before": func.greatest(revoked_grants.c.revoked_before, timestamp)}))
        fields = native._claim_values(claims, ("room_id", "member_id", "target_profile", "authority_gateway_id"))
        fields["authority_epoch"] = int(claims.get("authority_epoch") or 0)
        conn.execute(update(reservations).where(repo.key(reservations, store, fields)).values(revoked_at=timestamp, updated_at=timestamp))


def _live(store, room_id, target_profile, timestamp):
    return repo.key(reservations, store, dict(room_id=room_id, target_profile=target_profile)) & (
        reservations.c.expires_at > timestamp) & reservations.c.revoked_at.is_(None)


def reserve_peer_room(store, *, claims, expires_at, now=None):
    timestamp, expiry = clock(now), float(expires_at)
    if expiry <= timestamp:
        raise native.HostedRoomError("peer room reservation must expire in the future")
    room_id, member_id, profile, gateway, epoch = native._reservation_claims(claims)
    identity = dict(room_id=room_id, member_id=member_id, target_profile=profile)
    with store.write() as conn:
        repo.lock_store(conn, store)
        conn.execute(delete(reservations).where(repo.scope(reservations, store), reservations.c.expires_at <= timestamp))
        live = list(conn.execute(select(reservations).where(_live(store, room_id, profile, timestamp))).mappings())
        existing = conn.execute(select(reservations).where(repo.key(reservations, store, identity))).mappings().one_or_none()
        candidates = live + ([existing] if existing is not None else [])
        if any(native._reservation_superseded(repo.decode(row), gateway, epoch) for row in candidates):
            raise native.AuthorityConflictError("peer room reservation authority changed")
        conn.execute(update(reservations).where(repo.key(reservations, store, dict(room_id=room_id, target_profile=profile)),
            reservations.c.authority_epoch < epoch, reservations.c.revoked_at.is_(None)).values(revoked_at=timestamp, updated_at=timestamp))
        fields = dict(identity, authority_gateway_id=gateway, authority_epoch=epoch, expires_at=expiry,
                      revoked_at=None, created_at=timestamp, updated_at=timestamp)
        statement = insert(reservations).values(store_id=store.scope.require_store_id(), **repo.values(reservations, fields))
        updates = {name: statement.excluded[name] for name in ("authority_gateway_id", "authority_epoch", "revoked_at", "updated_at")}
        updates["expires_at"] = func.greatest(reservations.c.expires_at, expiry)
        conn.execute(statement.on_conflict_do_update(index_elements=[reservations.c.store_id, reservations.c.room_id,
            reservations.c.member_id, reservations.c.target_profile], set_=updates))


def peer_room_is_reserved(store, *, room_id, target_profile, now=None):
    room_id, profile = native._room_id(room_id), native._actor_id(target_profile, "target_profile")
    with store.read() as conn:
        return conn.scalar(select(reservations.c.room_id).where(_live(store, room_id, profile, clock(now))).limit(1)) is not None


def probe_peer_room_reservation(store, *, room_id, target_profile, now=None):
    return peer_room_is_reserved(store, room_id=room_id, target_profile=target_profile, now=now)


def peer_room_grant_is_current(store, *, claims, now=None):
    fields = dict(zip(("room_id", "member_id", "target_profile", "authority_gateway_id", "authority_epoch"),
                      native._reservation_claims(claims), strict=True))
    with store.read() as conn:
        return conn.scalar(select(reservations.c.room_id).where(repo.key(reservations, store, fields),
            reservations.c.expires_at > clock(now), reservations.c.revoked_at.is_(None))) is not None


def room_grant_is_revoked(store, *, claims, now=None):
    key = native._room_grant_scope_key(claims)
    with store.read() as conn:
        revoked = conn.scalar(select(revoked_grants.c.revoked_before).where(repo.scope(revoked_grants, store),
            revoked_grants.c.scope_key == key, revoked_grants.c.expires_at > clock(now)))
        return revoked is not None and float(claims.get("issued_at") or 0) <= revoked
