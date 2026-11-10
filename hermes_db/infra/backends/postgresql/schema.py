"""PostgreSQL schema inspection and explicit migration execution over supplied resources."""

from pathlib import Path

from hermes_db.errors import StorageSchemaError, StorageUnavailableError
from hermes_db.infra.backends.postgresql.engine import get_engine, require_postgresql_driver
from hermes_db.settings import PostgresSettings


def read_revision(conn, schema):
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


def missing_extensions(conn, required_extensions):
    from sqlalchemy import text

    query = text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname=:extension)")
    return [name for name in required_extensions if not conn.scalar(query, {"extension": name})]


def list_tables(conn, schema):
    from sqlalchemy import text

    return set(conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"),
                            {"schema": schema}).scalars())


def prepare_schema(conn, settings, *, required_extensions, missing_extension_action):
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
    if missing_extensions(conn, required_extensions):
        raise StorageSchemaError(missing_extension_action)
    exists = conn.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema})
    if not exists:
        conn.execute(CreateSchema(schema))
    if read_revision(conn, schema) is None:
        tables = list_tables(conn, schema)
        if tables - {"alembic_version"}:
            raise StorageSchemaError("Refusing to initialize a nonempty unversioned PostgreSQL schema")


def run_schema_upgrade(settings: PostgresSettings, *, migration_dir: Path, required_revision: str,
                       required_extensions: tuple[str, ...], schema_token: str,
                       missing_extension_action: str) -> None:
    """Execute only an explicit upgrade using caller-owned business resources."""
    sqlalchemy, _, _ = require_postgresql_driver()
    from alembic import command
    from alembic.config import Config
    from alembic.util.exc import CommandError

    config = Config(str(migration_dir / "alembic.ini"))
    config.set_main_option("script_location", str(migration_dir).replace("%", "%%"))
    config.attributes["schema"] = settings.schema
    try:
        with get_engine(settings).begin() as conn:
            prepare_schema(conn, settings, required_extensions=required_extensions,
                           missing_extension_action=missing_extension_action)
            config.attributes["connection"] = conn.execution_options(
                schema_translate_map={schema_token: settings.schema})
            command.upgrade(config, required_revision)
    except CommandError:
        raise StorageSchemaError("PostgreSQL schema revision is not supported by this Hermes version") from None
    except (sqlalchemy.exc.DBAPIError, sqlalchemy.exc.TimeoutError):
        raise StorageUnavailableError("PostgreSQL schema upgrade failed; check connectivity, permissions and db status before retrying") from None
