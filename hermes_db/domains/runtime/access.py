"""Driver-free runtime selection at ordinary service composition points."""

from hermes_db.health import is_postgresql_store


def runtime_for_store(store):
    return store.runtime


def effect_for_store(store, sqlite_effect, core_effect):
    if is_postgresql_store(store):
        from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
        return CoreEffect(core_effect)
    return sqlite_effect
