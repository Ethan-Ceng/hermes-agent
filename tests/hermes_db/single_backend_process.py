"""Fresh interpreter: all selected domains together, with no storage mocks or fallback."""

import json
import os
from pathlib import Path
import sys

from tests.hermes_db.single_backend_guard import install


def main():
    backend, role, *homes = sys.argv[1:]
    sqlite_matrix = "--matrix" in homes
    if sqlite_matrix:
        homes.remove("--matrix")
    attempts = install(backend, Path(homes[0]).parent / f"sqlite-attempt-{os.getpid()}", matrix=sqlite_matrix)
    from hermes_cli.db_setup import _owning_profile
    from tests.hermes_db.single_backend_core import DOMAINS
    from tests.hermes_db.single_backend_recovery import pg_plugins, retain
    for home in map(Path, homes):
        label = home.name + " 中文\x00🙂"
        manifest = home / "business-ids.json"
        saved = {} if role == "write" else json.loads(manifest.read_text(encoding="utf-8"))
        with _owning_profile(home):
            if backend == "sqlite" and role == "write":
                from hermes_cli.db_profile_schema import initialize_new_profile_storage
                initialize_new_profile_storage(home)
            completed = []
            for domain in DOMAINS:
                domain(home, label, role, saved)
                completed.append(domain.__name__)
            if backend == "postgresql":
                pg_plugins(home, label, role)
                completed.extend(("retain", "matrix"))
                from hermes_db.maintenance import maintain_profile
                maintain_profile(home)
            else:
                retain(home, label, role)
                completed.append("retain")
                if sqlite_matrix:
                    import asyncio
                    from tests.hermes_db.single_backend_recovery import matrix
                    asyncio.run(matrix(home, label, role, backend))
                    completed.append("matrix")
        if role == "write":
            manifest.write_text(json.dumps(saved), encoding="utf-8")
    if backend == "postgresql":
        assert not attempts
    else:
        blocked = {"sqlalchemy", "psycopg", "alembic"} | (set() if sqlite_matrix else {"asyncpg"})
        assert attempts and not any(name.split(".")[0] in blocked for name in sys.modules)
    print(json.dumps(dict(backend=backend, role=role, pid=os.getpid(), profiles=len(homes), domains=completed, sqlite_connections=len(attempts))))


if __name__ == "__main__":
    main()
