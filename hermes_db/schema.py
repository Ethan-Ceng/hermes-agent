"""Explicit schema upgrade and read-only version checks. No startup DDL."""

from pathlib import Path

from hermes_db.engine import get_engine, read_connection, require_postgresql_driver
from hermes_db.errors import StorageSchemaError, StorageUnavailableError
from hermes_db.settings import PostgresSettings

REQUIRED_REVISION = "0002_search_projection"


def _revision(conn, schema):
    from sqlalchemy import text

    exists = conn.scalar(text("SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                              "WHERE table_schema=:schema AND table_name='alembic_version')"), {"schema": schema})
    if not exists:
        return None
    quoted = conn.dialect.identifier_preparer.quote(schema)
    revisions = list(conn.execute(text(f"SELECT version_num FROM {quoted}.alembic_version")).scalars())
    if len(revisions) > 1:
        raise StorageSchemaError("PostgreSQL session schema has multiple revision heads")
    return revisions[0] if revisions else None


def schema_status(settings: PostgresSettings) -> dict:
    with read_connection(settings) as conn:
        revision = _revision(conn, settings.schema)
    return {"backend": "postgresql", "schema": settings.schema, "revision": revision,
            "required_revision": REQUIRED_REVISION, "ready": revision == REQUIRED_REVISION}


def check_schema(settings: PostgresSettings) -> None:
    if not schema_status(settings)["ready"]:
        raise StorageSchemaError("PostgreSQL session schema is incompatible; inspect hermes db status and run the explicit upgrade")


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
