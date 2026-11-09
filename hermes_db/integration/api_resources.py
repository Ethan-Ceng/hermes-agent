"""API auxiliary stores acquire the same configured session backend and owning scope."""

from hermes_db.core.session_resource import SessionResource


class OwnedApiStore:
    def __init__(self, store, resource):
        self._api_store, self._resource = store, resource

    def __getattr__(self, name):
        return getattr(self._api_store, name)

    def __len__(self):
        return len(self._api_store)

    @property
    def is_open(self):
        return self._resource.is_open and not self._api_store._closed

    def close(self):
        try:
            self._api_store.close()
        finally:
            self._resource.close()


def open_response_store(home, sqlite_factory, *, launch=False):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.factory import acquire_db
    settings, scope = resolve_db_configuration(home)
    if settings.backend == "sqlite":
        return sqlite_factory() if launch else sqlite_factory(db_path=str(scope.profile_home / "response_store.db"))
    from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
    resource = SessionResource(acquire_db(settings, scope))
    try:
        store = PostgresResponseStore(resource.session_store, initialize=False)
    except BaseException:
        resource.close()
        raise
    return OwnedApiStore(store, resource)


def open_run_store(home, sqlite_factory, *, launch=False):
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.factory import acquire_db
    settings, scope = resolve_db_configuration(home)
    if settings.backend == "sqlite":
        return sqlite_factory() if launch else sqlite_factory(db_path=str(scope.profile_home / "runs_idempotency.db"))
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    resource = SessionResource(acquire_db(settings, scope))
    try:
        store = PostgresRunIdempotencyStore(resource.session_store)
    except BaseException:
        resource.close()
        raise
    return OwnedApiStore(store, resource)
