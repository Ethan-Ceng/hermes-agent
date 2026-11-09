"""Explicit schema upgrade and read-only version checks. No startup DDL."""

from pathlib import Path

from hermes_db.backends.postgresql.engine import get_engine, read_connection, require_postgresql_driver
from hermes_db.errors import StorageSchemaError, StorageUnavailableError
from hermes_db.settings import PostgresSettings

REQUIRED_REVISION = "0031_merge_data_repair"
_PG_TRGM_ACTION = ("PostgreSQL pg_trgm is required. Connect to the configured database and run "
                   "CREATE EXTENSION IF NOT EXISTS pg_trgm; then run hermes db upgrade.")


def _revision(conn, schema):
    from sqlalchemy import text

    exists = conn.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                              "WHERE table_schema=:schema AND table_name='alembic_version')"), {"schema": schema})
    if not exists:
        return None
    quoted = conn.dialect.identifier_preparer.quote(schema)
    revisions = list(conn.execute(text(f"SELECT version_num FROM {quoted}.alembic_version")).scalars())
    if len(revisions) > 1:
        raise StorageSchemaError("PostgreSQL schema has multiple revision heads")
    return revisions[0] if revisions else None


def _missing_extensions(conn):
    from sqlalchemy import text
    installed = conn.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')"))
    return [] if installed else ["pg_trgm"]


def status_on_connection(conn, settings):
    from hermes_db.core.schema_status import domain_status_on_connection

    revision = _revision(conn, settings.schema)
    missing = _missing_extensions(conn)
    domains = domain_status_on_connection(conn, settings.schema, revision_ready=revision == REQUIRED_REVISION,
                                         extensions_ready=not missing)
    status = {"backend": "postgresql", "schema": settings.schema, "revision": revision,
        "required_revision": REQUIRED_REVISION, "missing_extensions": missing,
        "domains": domains, "full_system_ready": all(item["ready"] for item in domains.values()),
        "ready": all(item["ready"] for item in domains.values() if item["supported"])}
    if missing:
        status["action_required"] = _PG_TRGM_ACTION
    elif revision != REQUIRED_REVISION:
        status["action_required"] = "Inspect hermes db status and run the explicit hermes db upgrade."
    elif not status["ready"]:
        status["action_required"] = "Required domain tables are missing; inspect hermes db status and restore the schema."
    return status


def schema_status(settings: PostgresSettings) -> dict:
    with read_connection(settings) as conn:
        return status_on_connection(conn, settings)


def check_schema(settings: PostgresSettings) -> None:
    status = schema_status(settings)
    if not status["ready"]:
        raise StorageSchemaError("PostgreSQL schema is incompatible; " + status["action_required"])


def check_domain_schema(settings: PostgresSettings, name: str) -> None:
    from hermes_db.core.catalog import require_domain
    from hermes_db.errors import StorageNotReadyError

    require_domain(name)
    status = schema_status(settings)
    domain = status["domains"][name]
    if not domain["supported"]:
        raise StorageNotReadyError(f"PostgreSQL storage domain {name} is not implemented")
    if not domain["ready"]:
        raise StorageSchemaError(f"PostgreSQL storage domain {name} is not initialized; inspect hermes db status")


def _prepare_schema(conn, settings):
    from sqlalchemy import text
    from sqlalchemy.schema import CreateSchema

    schema = settings.schema
    locked = conn.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                         {"key": f"hermes-session-schema:{schema}"})
    if not locked:
        raise StorageSchemaError("Another process is upgrading this PostgreSQL schema")
    conn.execute(text("SELECT set_config('lock_timeout', :timeout, true)"),
                 {"timeout": str(max(1, int(settings.write_lock_timeout_seconds * 1000)))})
    conn.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                 {"timeout": str(max(1, int(settings.statement_timeout_seconds * 1000)))})
    if _missing_extensions(conn):
        raise StorageSchemaError(_PG_TRGM_ACTION)
    exists = conn.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema})
    if not exists:
        conn.execute(CreateSchema(schema))
    if _revision(conn, schema) is None:
        tables = set(conn.execute(text("SELECT table_name FROM information_schema.tables "
                                       "WHERE table_schema=:schema"), {"schema": schema}).scalars())
        if tables - {"alembic_version"}:
            raise StorageSchemaError("Refusing to initialize a nonempty unversioned PostgreSQL schema")


def upgrade_schema(settings: PostgresSettings) -> dict:
    sqlalchemy, _, _ = require_postgresql_driver()
    from alembic import command
    from alembic.config import Config
    from alembic.util.exc import CommandError

    migration_dir = Path(__file__).parent / "migrations"
    config = Config(str(migration_dir / "alembic.ini"))
    config.set_main_option("script_location", str(migration_dir).replace("%", "%%"))
    config.attributes["schema"] = settings.schema
    try:
        with get_engine(settings).begin() as conn:
            _prepare_schema(conn, settings)
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
    except CommandError:
        raise StorageSchemaError("PostgreSQL schema revision is not supported by this Hermes version") from None
    except (sqlalchemy.exc.DBAPIError, sqlalchemy.exc.TimeoutError):
        raise StorageUnavailableError("PostgreSQL schema upgrade failed; check connectivity, permissions and db status before retrying") from None
    return schema_status(settings)
