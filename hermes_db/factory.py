"""Select one explicit backend; acquisition failures never fall back."""

from hermes_db.handle import DatabaseHandle
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings


def acquire_db(settings: DatabaseSettings, scope: DatabaseScope) -> DatabaseHandle:
    if settings.backend == "sqlite":
        from hermes_db.legacy_sqlite import acquire_sqlite

        return acquire_sqlite(scope)
    scope.require_store_id()
    from hermes_db.engine import require_postgresql_driver

    require_postgresql_driver()
    from hermes_db.native_registry import acquire
    return acquire(settings.postgresql, scope)
