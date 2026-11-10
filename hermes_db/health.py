"""Driver-free identity helpers and read-only checks for configured PG storage."""

from pathlib import Path

from hermes_db.scope import DatabaseScope


def profile_home_for_store(store):
    scope = getattr(store, "scope", None)
    return scope.profile_home if isinstance(scope, DatabaseScope) else Path(store.db_path).resolve().parent


def is_postgresql_store(store):
    scope = getattr(store, "scope", None)
    return isinstance(scope, DatabaseScope) and scope.store_id is not None


def storage_identity(store):
    if is_postgresql_store(store):
        from hermes_db.core.values import resource_key
        return ("postgresql", resource_key(store._transactions), store.scope.require_store_id())
    return Path(store.db_path).resolve()


def own_profile_for_store(store):
    return store._own_profile if is_postgresql_store(store) else store._own_profile_name()


def persisted_profile_id(authority):
    if is_postgresql_store(authority.db):
        return "pg-store:" + authority.db.scope.require_store_id()
    return authority.profile_id
