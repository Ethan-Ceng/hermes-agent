"""Physical recovery is an explicit SQLite-only capability."""


def require_sqlite_recovery():
    from hermes_cli.db_setup import storage_backend
    from hermes_cli.session_recovery import SessionRecoverySafetyError
    if storage_backend() != "sqlite":
        raise SessionRecoverySafetyError("Session file recovery is SQLite-only; PostgreSQL recovery is operator-managed")
