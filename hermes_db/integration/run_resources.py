"""Run stores bind authenticated API scopes to immutable owning profile resources."""

from contextlib import ExitStack
from threading import RLock

from hermes_db.integration.api_resources import OwnedApiStore, open_run_store
from hermes_db.errors import StorageClosedError, StorageConfigurationError
from hermes_db.health import is_postgresql_store


def _home():
    from hermes_constants import get_hermes_home
    return get_hermes_home().resolve()


class ProfileRunStores:
    def __init__(self, sqlite_factory):
        from hermes_cli.db_setup import storage_backend
        self._root = _home()
        self._root_sqlite = storage_backend(self._root) == "sqlite"
        self._sqlite_factory = sqlite_factory
        self._stores = {self._root: open_run_store(self._root, sqlite_factory, launch=True)}
        self._scopes = {}
        self._lock, self._closed = RLock(), False

    def _require_open(self):
        if self._closed:
            raise StorageClosedError("API Run resources are closed")

    def _home_store(self, home):
        from hermes_cli.db_setup import storage_backend
        with self._lock:
            self._require_open()
            found = self._stores.get(home)
            if found is not None and (not isinstance(found, OwnedApiStore) or found.is_open):
                return found
        if home != self._root and self._root_sqlite and storage_backend(home) == "sqlite":
            # Original SQLite runs keep their profile-qualified scopes in the launch store.
            candidate = self._home_store(self._root)
            shared = True
        else:
            candidate = open_run_store(home, self._sqlite_factory, launch=home == self._root)
            shared = False
        with self._lock:
            closed = self._closed
            found = self._stores.get(home)
            retired = None
            if not closed and (found is None or isinstance(found, OwnedApiStore) and not found.is_open):
                retired = found
                self._stores[home] = candidate
                found = candidate
        if retired is not None:
            retired.close()
        if closed or found is not candidate:
            if not shared:
                candidate.close()
        if closed:
            raise StorageClosedError("API Run resources are closed")
        return found

    def _for_scope(self, scope):
        home = _home()
        with self._lock:
            self._require_open()
            previous = self._scopes.get(scope)
            if previous is not None and previous[0] != home:
                raise StorageConfigurationError("Authenticated API scope resolved to another profile")
        store = self._home_store(home)
        with self._lock:
            self._require_open()
            self._scopes[scope] = home, store
        return store

    def _known_scope(self, scope):
        with self._lock:
            self._require_open()
            found = self._scopes.get(scope)
        if found is None:
            raise StorageConfigurationError("An authenticated API scope is required for a Run update")
        return found[1]

    @property
    def durable(self):
        return self._home_store(_home()).durable

    def is_native_scope(self, scope):
        return is_postgresql_store(self._known_scope(scope))

    def reserve(self, scope, *args, **kwargs):
        return self._for_scope(scope).reserve(scope, *args, **kwargs)

    def lookup(self, scope, *args, **kwargs):
        return self._for_scope(scope).lookup(scope, *args, **kwargs)

    def find_or_close(self, scope, key):
        return self._for_scope(scope).find_or_close(scope, key)

    def status_for_run(self, scope, *args, **kwargs):
        return self._for_scope(scope).status_for_run(scope, *args, **kwargs)

    def extend_retention(self, scope, *args, **kwargs):
        return self._for_scope(scope).extend_retention(scope, *args, **kwargs)

    def owns_run(self, scope, *args, **kwargs):
        return self._for_scope(scope).owns_run(scope, *args, **kwargs)

    def forget(self, scope, key):
        return self._known_scope(scope).forget(scope, key)

    def update_status(self, run_id, status, *, scope):
        store = self._known_scope(scope)
        if is_postgresql_store(store):
            return store.update_status(run_id, status, scope=scope)
        return store.update_status(run_id, status)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            stores = {id(store): store for store in self._stores.values()}
            self._stores.clear()
            self._scopes.clear()
        with ExitStack() as stack:
            for store in stores.values():
                stack.callback(store.close)
