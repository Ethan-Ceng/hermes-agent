"""Profile database configuration; DSNs remain in profile secret sources."""

# Shared/weak-fsync filesystems can select delete journaling. None keeps
# SQLite's own WAL autocheckpoint and journal size defaults.
DATABASE_CONFIG = {"journal_mode": "wal", "wal_autocheckpoint": None, "journal_size_limit": None}

STORAGE_CONFIG = {
    "backend": "sqlite",
    "postgresql": {
        "dsn_env": "HERMES_POSTGRES_DSN",
        "schema": "",
        "store_id": "",
        "pool_size": 5,
        "max_overflow": 5,
        "pool_timeout_seconds": 30,
        "connect_timeout_seconds": 10,
        "write_lock_timeout_seconds": 10,
        "statement_timeout_seconds": 60,
        # Per process; deployments budget the sum over processes and replicas.
        "connection_budget": 10,
    },
}
