"""Purge a removed profile's bookkeeping while preserving transcript history."""

import time

from sqlalchemy import or_

from hermes_db.integration.postgres.operations.profile_repair import delete_routes
from hermes_db.repositories import gateway, sessions
from hermes_db.tables.gateway import delivery_obligations, gateway_heartbeats
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings, telegram_dm_topic_mode as modes


def purge(conn, scope, profile):
    from gateway.session import _session_key_namespace
    name = (profile or "").strip()
    if not name:
        return {}
    sessions.lock_store(conn, scope, exclusive=True)
    prefix = _session_key_namespace(name) + ":"
    routes = [(row["scope"], row["session_key"]) for row in gateway.routing_rows(conn, scope) if row["session_key"].startswith(prefix)]
    delete_routes(conn, scope, routes)
    owned = scope.require_store_id()
    counts = {"gateway_routing": len(routes)}
    counts["gateway_heartbeats"] = conn.execute(gateway_heartbeats.delete().where(
        gateway_heartbeats.c.store_id == owned, gateway_heartbeats.c.profile == name)).rowcount
    counts["delivery_obligations"] = conn.execute(delivery_obligations.update().where(
        delivery_obligations.c.store_id == owned,
        or_(delivery_obligations.c.adapter_profile == name, delivery_obligations.c.session_key.startswith(prefix, autoescape=True)),
        delivery_obligations.c.state.not_in(("delivered", "abandoned"))).values(state="abandoned", updated_at=time.time())).rowcount
    counts["telegram_dm_topic_mode"] = conn.execute(modes.delete().where(modes.c.store_id == owned, modes.c.profile_name == name)).rowcount
    counts["telegram_dm_topic_bindings"] = conn.execute(bindings.delete().where(bindings.c.store_id == owned,
        or_(bindings.c.profile_name == name, bindings.c.session_key.startswith(prefix, autoescape=True)))).rowcount
    return counts
