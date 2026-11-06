"""Driver-free identity helpers and read-only checks for configured PG storage."""

from pathlib import Path

from hermes_db.scope import DatabaseScope


def profile_home_for_store(store):
    scope = getattr(store, "scope", None)
    return scope.profile_home if isinstance(scope, DatabaseScope) else Path(store.db_path).resolve().parent


def is_postgresql_store(store):
    scope = getattr(store, "scope", None)
    return isinstance(scope, DatabaseScope) and scope.store_id is not None


def configured_probe(home):
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from hermes_cli.db_setup import resolve_db_configuration

    try:
        settings, scope = resolve_db_configuration(home)
        if settings.backend == "sqlite":
            return None
        from sqlalchemy import select
        from hermes_db.engine import read_connection
        from hermes_db.errors import StorageSchemaError
        from hermes_db.profile_context import OwnedProfileContext
        from hermes_db.schema import REQUIRED_REVISION, _revision
        from hermes_db.tables.conversations import sessions
        from hermes_db.tables.metadata import SCHEMA

        with OwnedProfileContext(scope).activate(), read_connection(settings.postgresql) as conn:
            if _revision(conn, settings.postgresql.schema) != REQUIRED_REVISION:
                raise StorageSchemaError("Schema upgrade required")
            conn = conn.execution_options(schema_translate_map={SCHEMA: settings.postgresql.schema})
            conn.execute(select(sessions.c.id).where(sessions.c.store_id == scope.require_store_id()).limit(1)).first()
        return {"backend": "postgresql", "status": "ok"}
    except (ConfigBackendUnavailable, Exception) as exc:  # health: allow BLE001 -- diagnostics redact every backend/config failure
        return {"status": "degraded", "detail": type(exc).__name__}
