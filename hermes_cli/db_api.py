"""Application acquisition for API auxiliary stores using the selected Profile backend."""

from hermes_db.domains.sessions.resource import SessionResource
from hermes_db.domains.runtime.resources import OwnedApiStore

def open_response_store(home, sqlite_factory):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_cli.db_sessions import acquire_db
    settings, scope = resolve_db_configuration(home)
    if settings.backend == "sqlite":
        return sqlite_factory.open_existing(db_path=str(scope.profile_home / "response_store.db"))
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    resource = SessionResource(acquire_db(settings, scope))
    try:
        store = PostgresResponseStore(resource.session_store, initialize=False)
    except BaseException:
        resource.close()
        raise
    return OwnedApiStore(store, resource)


def open_run_store(home, sqlite_factory):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_cli.db_sessions import acquire_db
    settings, scope = resolve_db_configuration(home)
    if settings.backend == "sqlite":
        return sqlite_factory.open_existing(db_path=str(scope.profile_home / "runs_idempotency.db"))
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    resource = SessionResource(acquire_db(settings, scope))
    try:
        store = PostgresRunIdempotencyStore(resource.session_store)
    except BaseException:
        resource.close()
        raise
    return OwnedApiStore(store, resource)
