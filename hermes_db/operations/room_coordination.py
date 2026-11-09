"""Canonical room ownership and admission facts on the FIFO writer's connection."""

from sqlalchemy import select
from gateway.owner_identity import same_owner
from gateway import hosted_rooms as native, hosted_room_driver as driver
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.repositories import rooms as room_repo, room_runs
from hermes_db.tables.runtime import state_meta
from hermes_db.tables.rooms import rooms, retired
from hermes_state_runtime import RuntimeStoreError

OWNER_PREFIX = "gateway.hosted.owner.v1:"


def owner(conn, scope, room_id):
    return runtime.meta(conn, scope, OWNER_PREFIX + room_id)


def owners(conn, scope):
    return tuple(value[len(OWNER_PREFIX):] for value in conn.execute(select(state_meta.c.key).where(
        state_meta.c.store_id == scope.require_store_id(), state_meta.c.key.startswith(OWNER_PREFIX, autoescape=True))).scalars())


def authorize_room(conn, store, epoch, subject, room_id, *, create=False):
    runtime.require_epoch(conn, store.scope, epoch)
    room_repo.lock_store(conn, store)
    saved = owner(conn, store.scope, room_id)
    if saved is None and create:
        historical = any(conn.scalar(select(table.c.room_id).where(room_repo.scope(table, store, room_id))) is not None
                         for table in (rooms, retired))
        if not historical:
            runtime.set_meta(conn, store.scope, OWNER_PREFIX + room_id, subject)
            return True
    if saved is None or not same_owner(saved, subject):
        raise RuntimeStoreError("permission_denied")
    return True


def member_authorized(conn, store, epoch, *, owner_subject, binding, member_id, profile, operation, identity, generation):
    runtime.require_epoch(conn, store.scope, epoch)
    room_repo.lock_store(conn, store)
    if owner(conn, store.scope, binding.room_id) != owner_subject:
        return False
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, binding.room_id)).with_for_update()).mappings().one_or_none()
    if row is None or row["disbanded_at"] is not None:
        return False
    room = native._room_from_row(room_repo.decode(row))
    if (room["authority_gateway_id"], room["authority_epoch"]) != (binding.gateway_id, binding.authority_epoch):
        return False
    if not any(member.get("member_id") == member_id and member.get("profile") == profile
               and (member.get("target") or {}).get("kind", "local") == "local" for member in room["members"]):
        return False
    if identity is None:
        return True
    if identity.room_id != binding.room_id:
        return False
    try:
        row = room_runs.task(conn, store, identity, required=False)
    except driver.TaskConflictError:
        return False
    if row is None:
        return False
    task = driver._task_from_row(row)
    return (task["identity"] == identity and task["execution_generation"] == generation
            and task["payload"]["target_profile"] == profile
            and task["payload"].get("target_member_id", profile) == member_id
            and task["status"] in ({"running"} if operation in {"submit", "execute"} else {"running", "stopping"}))
