"""Selected-backend Desktop preflight; low-level SQLite emergency copying stays standalone."""

from pathlib import Path
import json
import signal
import sys


def preflight(home):
    from hermes_cli.db_setup import storage_backend
    backend = storage_backend(home)
    if backend == "postgresql":
        return {"backend": backend, "path": None, "database_included": False,
            "message": "PostgreSQL system database data is excluded; database backup and restore are operator-managed"}
    from hermes_cli.backup_sqlite import preflight_state_db
    result = preflight_state_db(Path(home))
    return {"backend": backend, "database_included": result["path"] is not None, **result}


if __name__ == "__main__":
    # -I retains the selected interpreter's dependencies; only this trusted checkout is added.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    signal.signal(signal.SIGTERM, lambda signum, _frame: sys.exit(128 + signum))
    print(json.dumps(preflight(Path(sys.argv[1]))))
