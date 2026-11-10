"""Closed tool-read operations for an adopted worker, never a SQL or path RPC."""

import asyncio

from hermes_state_runtime import RuntimeStoreError
from tools.session_store_reads import cron_run_usage, owns_result, persisted_session
from gateway.session_worker_domains import storage_identity

_READS = {
    "storage.identity": (storage_identity, set()),
    "result.owns": (owns_result, {"owner", "parent"}),
    "session.persisted": (persisted_session, {"session_id"}),
    "cron.usage": (cron_run_usage, {"job_id", "execution_id"}),
}


async def worker_read(connection, ref, params):
    from gateway.session_authorities import require_serving
    from gateway.session_worker import _SCOPE
    require_serving(connection.authority)
    if set(params) != _SCOPE | {"epoch", "operation", "payload"}:
        raise RuntimeStoreError("invalid_params")
    if "worker:adopt" not in connection.actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    operation, payload = params["operation"], params["payload"]
    if operation == 'domain.read' and isinstance(payload, dict):
        from gateway.session_worker_domains import worker_domain_read
        return await worker_domain_read(connection, ref, params)
    if not isinstance(operation, str) or operation not in _READS or not isinstance(payload, dict):
        raise RuntimeStoreError("invalid_params")
    handler, fields = _READS[operation]
    if set(payload) != fields or any(not isinstance(value, str) or not value or len(value) > 1024 for value in payload.values()):
        raise RuntimeStoreError("invalid_params")
    return await asyncio.to_thread(_read, connection, ref, params, handler)


def _read(connection, ref, params, handler):
    from gateway.session_worker_recall import verify_read
    from hermes_db.health import profile_home_for_store
    from hermes_db.scope import DatabaseScope
    from hermes_cli.db_scope import bind_profile_home
    verify_read(connection, ref, params)
    db = connection.authority.db
    with bind_profile_home(DatabaseScope(profile_home_for_store(db))):
        return handler(db, **params["payload"])
