"""Explicit schema upgrade and read-only version checks. No startup DDL."""

from pathlib import Path

from hermes_db.infra.backends.postgresql.engine import read_connection
from hermes_db.infra.backends.postgresql import schema as pg_schema
from hermes_db.errors import StorageSchemaError
from hermes_db.settings import PostgresSettings

REQUIRED_REVISION = "0031_merge_data_repair"
REQUIRED_EXTENSIONS = ("pg_trgm",)
_PG_TRGM_ACTION = ("PostgreSQL pg_trgm is required. Connect to the configured database and run "
                   "CREATE EXTENSION IF NOT EXISTS pg_trgm; then run hermes db upgrade.")


def status_on_connection(conn, settings):
    from hermes_db.domains.schema_status import domain_status_on_connection

    revision = pg_schema.read_revision(conn, settings.schema)
    missing = pg_schema.missing_extensions(conn, REQUIRED_EXTENSIONS)
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



def upgrade_schema(settings: PostgresSettings) -> dict:
    from hermes_db.tables.metadata import SCHEMA

    pg_schema.run_schema_upgrade(
        settings, migration_dir=Path(__file__).parent / "migrations", required_revision=REQUIRED_REVISION,
        required_extensions=REQUIRED_EXTENSIONS, schema_token=SCHEMA, missing_extension_action=_PG_TRGM_ACTION,
    )
    return schema_status(settings)
