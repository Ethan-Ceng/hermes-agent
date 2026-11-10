"""Driver-free runtime selection at ordinary service composition points."""

from hermes_db.health import is_postgresql_store, profile_home_for_store
from hermes_db.scope import DatabaseScope
from hermes_db.domains.sessions.resource import SessionResource


def runtime_for_store(store):
    if isinstance(store, SessionResource):
        return store.runtime
    if is_postgresql_store(store):
        from hermes_db.integration.runtime_composition import create_runtime_store
        return create_runtime_store(store)
    from hermes_db.domains.runtime.sqlite import SQLiteRuntime
    from functools import partial
    from hermes_cli.db_scope import bind_profile_home
    from hermes_cli.db_sessions import _native_runtime_function
    scope = DatabaseScope(profile_home_for_store(store))
    return SQLiteRuntime(store, scope, activate=partial(bind_profile_home, scope), resolve=_native_runtime_function)


def effect_for_store(store, sqlite_effect, core_effect):
    if is_postgresql_store(store):
        from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
        return CoreEffect(core_effect)
    return sqlite_effect
