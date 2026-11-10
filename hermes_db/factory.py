"""Select one explicit backend; acquisition failures never fall back."""

from hermes_db.handle import DatabaseHandle
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings


def acquire_db(settings: DatabaseSettings, scope: DatabaseScope) -> DatabaseHandle:
    if settings.backend == "sqlite":
        from hermes_db.backends.sqlite.acquire import acquire_sqlite

        return acquire_sqlite(scope)
    scope.require_store_id()
    from hermes_db.infra.backends.postgresql.engine import require_postgresql_driver

    require_postgresql_driver()
    from hermes_db.integration.registry import acquire
    return acquire(settings.postgresql, scope)


def acquire_domain(name, settings: DatabaseSettings, scope: DatabaseScope, *, sqlite_path=None):
    """Explicit owner scope; a domain file path never selects the Profile/backend."""
    from hermes_db.access import _owner_only
    from hermes_db.core.catalog import POSTGRES_DOMAINS, require_domain
    from hermes_db.core.resource import DomainResource
    from hermes_db.errors import StorageNotReadyError

    _owner_only()
    require_domain(name)
    if settings.backend == "sqlite":
        return DomainResource(name, settings, scope, sqlite_path=sqlite_path)
    scope.require_store_id()
    if name not in POSTGRES_DOMAINS:
        raise StorageNotReadyError(f"PostgreSQL storage domain {name} is not implemented")
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.schema import check_domain_schema
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA

    pg = settings.postgresql
    check_domain_schema(pg, name)
    transactions = Transactions(get_engine(pg), pg.schema, lock_timeout=pg.write_lock_timeout_seconds,
                                statement_timeout=pg.statement_timeout_seconds, schema_token=SCHEMA)
    from hermes_db.integration.domain_composition import create_domain_resource
    return create_domain_resource(name, settings, scope, transactions=transactions)


def acquire_profile_domain(name, *, profile_home=None, sqlite_path=None):
    from hermes_cli.db_setup import resolve_db_configuration

    settings, scope = resolve_db_configuration(profile_home)
    return acquire_domain(name, settings, scope, sqlite_path=sqlite_path)
