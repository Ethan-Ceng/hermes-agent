"""Opt-in test database access and ownership of disposable PostgreSQL schemas."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from hermes_db.settings import PostgresSettings


class PostgresTestError(RuntimeError):
    """A test prerequisite or namespace ownership check failed."""


@dataclass(frozen=True)
class PostgresTestConfig:
    settings: PostgresSettings
    database: str


def read_test_config(path: str | None) -> PostgresTestConfig:
    from hermes_yaml import YAMLError, safe_load

    if not path:
        raise PostgresTestError("Real PostgreSQL tests require --postgres-test-config with an independent test database")
    try:
        raw = safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, YAMLError):
        raise PostgresTestError("PostgreSQL test config cannot be read or parsed; credential details are suppressed") from None
    if not isinstance(raw, dict) or raw.get("purpose") != "hermes-postgresql-tests":
        raise PostgresTestError("Test config must explicitly declare purpose: hermes-postgresql-tests")
    database = raw.get("database")
    if not isinstance(database, str) or not database or database in ("postgres", "template0", "template1"):
        raise PostgresTestError("Test config must name an independent database, excluding PostgreSQL maintenance databases")
    try:
        settings = PostgresSettings(raw.get("dsn", ""), "hermes_test_control", pool_size=2,
                                    max_overflow=0, connection_budget=2, pool_timeout_seconds=5,
                                    connect_timeout_seconds=5)
        if urlsplit(settings.dsn).scheme not in ("postgres", "postgresql", "postgresql+psycopg"):
            raise ValueError("unsupported test driver")
    except ValueError:
        raise PostgresTestError("PostgreSQL test config requires a DSN secret") from None
    return PostgresTestConfig(settings, database)


def verify_database(actual: str, expected: str):
    if actual != expected:
        raise PostgresTestError("Connected database does not match the explicitly allowed test database")


def probe_environment(conn, config):
    from sqlalchemy import text

    verify_database(conn.scalar(text("SELECT current_database()")), config.database)
    version = int(conn.scalar(text("SHOW server_version_num")))
    if version < 150000:
        raise PostgresTestError("PostgreSQL tests require version 15 or newer")
    if not conn.scalar(text("SELECT has_database_privilege(current_user, current_database(), 'CREATE')")):
        raise PostgresTestError("Test database role needs CREATE permission for disposable test schemas")
    extension_schema = conn.scalar(text(
        "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pg_trgm'"))
    if extension_schema is None:
        raise PostgresTestError("Administrator must prepare pg_trgm in the independent test database; tests never install extensions")
    tls = conn.execute(text("SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid=pg_backend_pid()")).mappings().one_or_none()
    return {"server_version_num": version, "pg_trgm_schema": extension_schema,
            "tls": dict(tls) if tls else {"ssl": False}}


@contextmanager
def isolated_namespace(engine, config):
    """Never reuse a schema, and refuse cleanup if the ownership marker changed."""
    from sqlalchemy import DDL, text
    from sqlalchemy.schema import CreateSchema, DropSchema

    token = uuid4().hex
    schema = "hermes_test_" + token
    marker = "hermes-pg-tests:" + token
    with engine.begin() as conn:
        verify_database(conn.scalar(text("SELECT current_database()")), config.database)
        if conn.scalar(text("SELECT oid FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}) is not None:
            raise PostgresTestError("Disposable schema already exists; refusing to adopt or delete it")
        conn.execute(CreateSchema(schema))
        quoted = conn.dialect.identifier_preparer.quote(schema)
        # Both marker and schema are generated here, never taken from the file.
        conn.execute(DDL(f"COMMENT ON SCHEMA {quoted} IS '{marker}'"))
    try:
        yield schema
    finally:
        with engine.begin() as conn:
            actual = conn.scalar(text(
                "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname=:schema"),
                {"schema": schema})
            if actual != marker:
                raise PostgresTestError("Test schema ownership changed; refusing cleanup")
            conn.execute(DropSchema(schema, cascade=True))
