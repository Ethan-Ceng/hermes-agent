"""Current imported/history ownership checks, never SQLite legacy adoption."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import mutation_binding, retirement, sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.domains.runtime.values import RuntimeStoreError


def authorize_claim(conn, scope, actor, sid, *, own_profile, native_transport, ownership):
    row = sessions.raw_session(conn, scope, sid)
    if row is None or row["session_key"] or row["chat_id"] or row["origin_json"]:
        return False
    binding = mutation_binding.history_binding(conn, scope, sid)
    own = row["profile_name"] in (None, "", own_profile or "default")
    if binding is None and not (own and ownership.owner_user(row) and ownership.same_owner(row["user_id"], actor.subject)) and not native_transport:
        raise RuntimeStoreError("permission_denied")
    return mutation_binding.authorize_history(conn, scope, actor, sid, ownership=ownership)


def require_leaf(conn, scope, sid, chain, *, ownership):
    chain = set(chain)
    targets = retirement.canonical_targets(conn, scope, sid, ownership=ownership)
    children = conn.execute(select(table.c.id).where(table.c.store_id == scope.require_store_id(),
        table.c.parent_session_id.in_(targets))).scalars()
    if not chain.issuperset([*targets, *children]):
        raise RuntimeStoreError("session_has_children", field="session_id",
            detail="this stored conversation has child sessions a delete would take with it")
