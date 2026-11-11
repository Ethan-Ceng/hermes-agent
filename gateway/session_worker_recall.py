"""Authenticated profile-owned recall; compute receives only the tool result."""

import asyncio

from hermes_state_runtime import RuntimeStoreError

_OPTIONS = {"query", "role_filter", "limit", "current_session_id", "session_id", "around_message_id",
    "window", "sort", "profile", "detail", "after", "before", "exclude_session_ids"}


async def worker_recall(connection, ref, params):
    from gateway.session_authorities import require_serving
    from gateway.session_worker import _SCOPE
    authority = connection.authority
    require_serving(authority)
    if set(params) != _SCOPE | {"epoch", "options"} or not isinstance(params["options"], dict):
        raise RuntimeStoreError("invalid_params")
    if set(params["options"]) - _OPTIONS:
        raise RuntimeStoreError("invalid_params")
    if "worker:adopt" not in connection.actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    return await asyncio.to_thread(_recall, connection, ref, params)


def _recall(connection, ref, params):
    from tools.session_search_tool import session_search
    verify_read(connection, ref, params)
    # The RPC carries tool options only. Profile resolution stays at the owner;
    # no worker may select a DSN, schema, store_id or local database filename.
    from hermes_db.health import profile_home_for_store
    from hermes_db.scope import DatabaseScope
    from hermes_cli.db_scope import bind_profile_home
    with bind_profile_home(DatabaseScope(profile_home_for_store(connection.authority.db))):
        return session_search(db=connection.authority.db, **params["options"])


def verify_read(connection, ref, params):
    if type(params.get("epoch")) is not int:
        raise RuntimeStoreError("invalid_params")
    from gateway.session_worker import _claim, _verify
    from hermes_db.health import is_postgresql_store
    from hermes_db.domains.runtime.access import runtime_for_store
    authority = connection.authority
    claim = _claim(connection, ref, params)
    if is_postgresql_store(authority.db):
        runtime_for_store(authority.db).verify_worker_claim(params, claim, active_epoch=authority.epoch)
    else:
        _verify(connection, ref, params, claim)
        from hermes_state_runtime import _epoch
        with authority.db._read_ctx() as conn:
            _epoch(conn, params["epoch"])
            row = conn.execute("SELECT status,owner_epoch FROM worker_executions WHERE execution_id=?",
                (params["execution_id"],)).fetchone()
            if row["status"] != "running" or row["owner_epoch"] != params["epoch"]:
                raise RuntimeStoreError("stale_generation")
