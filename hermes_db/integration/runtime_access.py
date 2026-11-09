"""Driver-free runtime selection at ordinary service composition points."""

from hermes_db.health import is_postgresql_store, profile_home_for_store
from hermes_db.scope import DatabaseScope
from hermes_db.core.session_resource import SessionResource


def runtime_for_store(store):
    if isinstance(store, SessionResource):
        return store.runtime
    if is_postgresql_store(store):
        from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore
        return PostgresRuntimeStore(store)
    from hermes_db.backends.sqlite.acquire import SQLiteRuntime
    return SQLiteRuntime(store, DatabaseScope(profile_home_for_store(store)))


def effect_for_store(store, sqlite_effect, core_effect):
    if is_postgresql_store(store):
        from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
        return CoreEffect(core_effect)
    return sqlite_effect
