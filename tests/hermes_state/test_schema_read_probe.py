"""Validate that ordinary readiness SELECTs cover every declared table and column.

Compare them against SQLite's interpretation of SCHEMA_SQL on a scratch store.
Ordinary opens use the generated column declarations and never execute scratch DDL.
"""

import sqlite3

import pytest

from hermes_state_common import DEFERRED_INDEX_SQL, SCHEMA_SQL
from hermes_state_schema import SessionSchemaMixin, schema_read_probe_statements

def _fresh_schema_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    conn.executescript(DEFERRED_INDEX_SQL)
    return conn

class TestSchemaReadProbeStatements:
    def test_probes_cover_every_declared_column(self):
        """Schema additions must update the generated read probe declarations."""
        expected = SessionSchemaMixin._parse_schema_columns(SCHEMA_SQL)
        statements = schema_read_probe_statements()
        by_table = {}
        for statement in statements:
            for table in expected:
                if f'FROM "{table}"' in statement:
                    by_table[table] = statement
        for table, cols in expected.items():
            assert table in by_table, f"no probe statement for table {table}"
            for col in cols:
                assert f'"{table}"."{col}"' in by_table[table], (
                    f"column {table}.{col} declared in SCHEMA_SQL but not probed"
                )

    def test_probes_pass_on_fresh_schema(self):
        conn = _fresh_schema_conn()
        try:
            for statement in schema_read_probe_statements():
                conn.execute(statement).fetchone()
        finally:
            conn.close()

    def test_probes_fail_on_missing_column(self):
        """The shipped regression: a store predating sessions.last_activity_at

        (#72424) passed the old hand-written probe, then 500'd inside
        list_sessions_rich on every sidebar poll until the user's first
        message forced a writable open.
        """
        conn = _fresh_schema_conn()
        try:
            # Indexes that depend on the column must be removed before SQLite
            # can emulate a pre-column legacy store via DROP COLUMN.
            conn.execute("DROP INDEX IF EXISTS idx_sessions_effective_activity")
            conn.execute("ALTER TABLE sessions DROP COLUMN last_activity_at")
            # The failure must come from the sessions probe naming the exact
            # column — not incidentally from some other statement — so a
            # probe-generation bug that misassigns columns to tables can't
            # sneak through.
            sessions_probe = next(
                s
                for s in schema_read_probe_statements()
                if 'FROM "sessions"' in s
            )
            with pytest.raises(sqlite3.OperationalError) as excinfo:
                conn.execute(sessions_probe)
            assert "no such column: sessions.last_activity_at" in str(
                excinfo.value
            )
        finally:
            conn.close()

    def test_probes_fail_on_missing_table(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executescript("DROP TABLE gateway_routing")
            gateway_probe = next(
                s
                for s in schema_read_probe_statements()
                if 'FROM "gateway_routing"' in s
            )
            with pytest.raises(sqlite3.OperationalError) as excinfo:
                conn.execute(gateway_probe)
            assert "no such table" in str(excinfo.value).lower()
        finally:
            conn.close()
