"""Ordinary session acquisition selects one backend and preserves SQLite file tooling."""

from pathlib import Path


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
    from hermes_db.factory import acquire_db
    from hermes_db.core.session_resource import SessionResource
    path = _path(db_path)
    settings, scope = resolve_db_configuration(path.resolve().parent)
    if settings.backend == "sqlite":
        from hermes_state_registry import acquire
        return acquire(None if db_path is None else path)
    return SessionResource(acquire_db(settings, scope))


def open_session_store(db_path=None, *, read_only=False):
    _owner_only()
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.factory import acquire_db
    from hermes_db.core.session_resource import SessionResource
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


def release_session_store(store):
    from hermes_db.core.session_resource import SessionResource
    if isinstance(store, SessionResource):
        store.close()
    else:
        from hermes_state_registry import release_or_close
        release_or_close(store)


def session_store_is_live(store):
    from hermes_db.core.session_resource import SessionResource
    if isinstance(store, SessionResource):
        return store.is_open
    return getattr(store, "_shared_registry_owned", True) is not False


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
