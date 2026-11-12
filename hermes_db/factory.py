"""Select a resolved technical backend without constructing business resources or running DDL."""

from pathlib import Path

from hermes_db.errors import StorageConfigurationError
from hermes_db.infra.resource import BackendResource
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings


def acquire_backend(settings: DatabaseSettings, scope: DatabaseScope, *, sqlite_path=None, schema_token=None):
    if settings.backend == "sqlite":
        return BackendResource(settings, scope, sqlite_path=Path(sqlite_path) if sqlite_path is not None else None)
    scope.require_store_id()
    if schema_token is None:
        raise StorageConfigurationError("PostgreSQL backend acquisition requires an explicit schema token")
    from hermes_db.infra.postgresql.engine import get_engine
    from hermes_db.infra.postgresql.transactions import Transactions

    pg = settings.postgresql
    transactions = Transactions(get_engine(pg), pg.schema, schema_token=schema_token,
                                lock_timeout=pg.write_lock_timeout_seconds,
                                statement_timeout=pg.statement_timeout_seconds)
    return BackendResource(settings, scope, transactions=transactions)
