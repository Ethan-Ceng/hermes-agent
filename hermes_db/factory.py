"""Select a backend once; an incomplete PostgreSQL backend never falls back."""

from hermes_db.errors import StorageNotReadyError
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
    # Removed only when all session/runtime/API/delivery capabilities are wired.
    raise StorageNotReadyError("PostgreSQL session storage is under development; activation is not yet supported")
