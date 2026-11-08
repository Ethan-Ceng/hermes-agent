"""Process-wide connection audit for business acceptance, including aliases and constructors."""

import importlib.abc
from pathlib import Path
import sqlite3
import sys


class WithoutPostgres(importlib.abc.MetaPathFinder):
    def __init__(self, *, sdk_types=False):
        self.blocked = {"sqlalchemy", "psycopg", "alembic"} | (set() if sdk_types else {"asyncpg"})

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self.blocked:
            raise ModuleNotFoundError("PostgreSQL dependency deliberately absent in SQLite acceptance")


def install(backend, witness, *, matrix=False):
    attempts = []
    witness = Path(witness)

    def observe(event, arguments):
        if event == "sqlite3.connect":
            attempts.append(True)
            if backend == "postgresql":
                witness.write_text("SQLITE_CONNECTION_ATTEMPT", encoding="utf-8")
                raise AssertionError("Every SQLite connection is forbidden in the PG business process")

    sys.addaudithook(observe)
    if backend == "sqlite":
        sys.meta_path.insert(0, WithoutPostgres(sdk_types=matrix))
        if matrix:
            # Upstream's SQLite SQL store imports asyncpg.UniqueViolationError.
            # Keep the real SDK types while proving it never connects to PostgreSQL.
            import asyncpg
            def reject_postgres(*args, **kwargs):
                witness.write_text("POSTGRES_CONNECTION_ATTEMPT", encoding="utf-8")
                raise AssertionError("PostgreSQL connection forbidden in SQLite SDK acceptance")
            asyncpg.connect = reject_postgres
            asyncpg.create_pool = reject_postgres
    return attempts
