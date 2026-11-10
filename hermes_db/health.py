"""Driver-free identity helpers and read-only checks for configured PG storage."""

from pathlib import Path

from hermes_db.scope import DatabaseScope


def profile_home_for_store(store):
    scope = getattr(store, "scope", None)
    return scope.profile_home if isinstance(scope, DatabaseScope) else Path(store.db_path).resolve().parent


def is_postgresql_store(store):
    scope = getattr(store, "scope", None)
    return isinstance(scope, DatabaseScope) and scope.store_id is not None


def storage_identity(store):
    if is_postgresql_store(store):
        from hermes_db.core.values import resource_key
        return ("postgresql", resource_key(store._transactions), store.scope.require_store_id())
    return Path(store.db_path).resolve()


def own_profile_for_store(store):
    return store._own_profile if is_postgresql_store(store) else store._own_profile_name()


def persisted_profile_id(authority):
    if is_postgresql_store(authority.db):
        return "pg-store:" + authority.db.scope.require_store_id()
    return authority.profile_id


def configured_probe(home):
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from hermes_cli.db_setup import resolve_db_configuration, storage_backend

    backend = "unknown"
    try:
        backend = storage_backend(home)
        if backend == "sqlite":
            return None
        settings, scope = resolve_db_configuration(home)
        from sqlalchemy import select
        from hermes_db.infra.backends.postgresql.engine import read_connection
        from hermes_db.errors import StorageSchemaError
        from hermes_db.integration.profile_context import OwnedProfileContext
        from hermes_db.schema import status_on_connection
        from hermes_db.tables.conversations import sessions
        from hermes_db.tables.metadata import SCHEMA

        with OwnedProfileContext(scope).activate(), read_connection(settings.postgresql) as conn:
            status = status_on_connection(conn, settings.postgresql)
            if not status["ready"]:
                raise StorageSchemaError(status["action_required"])
            conn = conn.execution_options(schema_translate_map={SCHEMA: settings.postgresql.schema})
            conn.execute(select(sessions.c.id).where(sessions.c.store_id == scope.require_store_id()).limit(1)).first()
        return {"backend": "postgresql", "status": "ok"}
    except (ConfigBackendUnavailable, Exception) as exc:  # health: allow BLE001 -- diagnostics redact every backend/config failure
        return {"backend": backend, "status": "degraded", "detail": type(exc).__name__}
