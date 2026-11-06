"""Local-file maintenance boundaries for the selected session backend."""


def _refuse(action):
    print(f"sessions {action} applies to local SQLite storage. PostgreSQL physical maintenance and backups are operator-managed; "
        "use `hermes db status` for connectivity/schema checks and `hermes db upgrade` for the declared schema upgrade.")
    return True


def refuse_physical_maintenance(store, action):
    from hermes_db.health import is_postgresql_store
    return _refuse(action) if is_postgresql_store(store) else False


def refuse_configured_physical_maintenance(home, action):
    from hermes_cli.db_setup import session_backend
    return _refuse(action) if session_backend(home) == "postgresql" else False
