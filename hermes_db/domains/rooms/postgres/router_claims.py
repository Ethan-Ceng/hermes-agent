"""Durable room router claim CAS and release on the supplied connection."""
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.rooms.postgres import repository as repo
from hermes_db.tables.room_policy import router_claims


def claim_router_call(conn, store, key, owner, now, ttl_seconds):
    fields = repo.values(router_claims, dict(room_id=key[0], discussion_event_id=key[1], owner=owner, expires_at=now + ttl_seconds))
    statement = insert(router_claims).values(store_id=store.scope.require_store_id(), **fields)
    claimed_owner = conn.scalar(statement.on_conflict_do_update(index_elements=list(router_claims.primary_key.columns),
        set_=dict(owner=statement.excluded.owner, expires_at=statement.excluded.expires_at),
        where=router_claims.c.expires_at <= now).returning(router_claims.c.owner))
    return claimed_owner == owner


def release_router_call(conn, store, key, owner):
    conn.execute(delete(router_claims).where(repo.key(router_claims, store, dict(room_id=key[0], discussion_event_id=key[1], owner=owner))))
