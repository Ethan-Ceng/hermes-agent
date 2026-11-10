"""Compose owner session acquisitions from an already resolved Profile configuration."""

from functools import partial
from pathlib import Path

from hermes_db.handle import DatabaseHandle
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings
from hermes_cli.db_scope import bind_profile_home


def _path(db_path):
    from hermes_constants import get_hermes_home
    return Path(db_path) if db_path is not None else get_hermes_home() / "state.db"


def _owner_only():
    from agent.runtime_session_store import WorkerPersistenceError, is_worker_process
    if is_worker_process():
        raise WorkerPersistenceError("owner_store_access_from_worker")


def acquire_sessions(db_path=None):
    _owner_only()
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.domains.sessions.resource import SessionResource
    path = _path(db_path)
    settings, scope = resolve_db_configuration(path.resolve().parent)
    if settings.backend == "sqlite":
        from hermes_state_registry import acquire
        return acquire(None if db_path is None else path)
    return SessionResource(acquire_db(settings, scope))


def open_session_store(db_path=None, *, read_only=False):
    _owner_only()
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.domains.sessions.resource import SessionResource
    path = _path(db_path)
    settings, scope = resolve_db_configuration(path.resolve().parent)
    if settings.backend == "sqlite":
        from hermes_state import SessionDB
        return SessionDB(db_path=None if db_path is None else path, read_only=read_only)
    return SessionResource(acquire_db(settings, scope))


def session_store_exists(db_path=None):
    """Whether to attempt an open; PG reachability is determined by that open."""
    from hermes_cli.db_setup import storage_backend
    path = _path(db_path)
    if storage_backend(path.resolve().parent) == "postgresql":
        return True
    from hermes_state import _default_db_path
    return (Path(_default_db_path()) if db_path is None else path).exists()


def close_session_resources_under(home):
    from hermes_db.integration.registry import close_all as close_native
    from hermes_state_registry import close_all_under
    return close_all_under(home) + close_native(home)


def close_session_resources():
    """The gateway calls this only after all producer/worker quiesce checks pass."""
    from hermes_db.infra.backends.postgresql.engine import close_engines
    from hermes_db.integration.registry import close_all as close_native
    from hermes_state_registry import close_all
    count = close_all() + close_native()
    close_engines()
    return count


def acquire_db(settings: DatabaseSettings, scope: DatabaseScope) -> DatabaseHandle:
    _owner_only()
    if settings.backend == "sqlite":
        from hermes_db.factory import acquire_backend

        backend = acquire_backend(settings, scope, sqlite_path=scope.profile_home / "state.db")
        return acquire_sqlite(backend)
    scope.require_store_id()
    from hermes_db.infra.backends.postgresql.engine import require_postgresql_driver

    require_postgresql_driver()
    from hermes_db.integration.registry import acquire
    return acquire(settings.postgresql, scope)


def _native_runtime_function(name):
    """Resolve the existing fixed runtime dispatch at the application facade patch seam."""
    import hermes_state_runtime
    return getattr(hermes_state_runtime, name)


def acquire_sqlite(backend):
    """Assemble native business adapters under their explicitly selected application owner."""
    from hermes_db.domains.resource import _bound_method
    from hermes_db.domains.sessions.sqlite import SQLiteSessions
    from hermes_db.domains.runtime.sqlite import SQLiteRuntime
    from hermes_state_registry import acquire, release

    scope = backend.scope
    activate = partial(bind_profile_home, scope)
    with activate():
        db = acquire(backend.sqlite_path)
    return DatabaseHandle(scope, SQLiteSessions(db, scope, activate=activate),
                          SQLiteRuntime(db, scope, activate=activate, resolve=_native_runtime_function),
                          _bound_method(activate, release, db))
