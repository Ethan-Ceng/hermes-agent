"""All domains together, two isolated stores, actual SDK crypto and fresh-process recovery."""

import pytest
from tests.hermes_db.single_backend_support import prepare_workspace, run

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.platforms("linux")]


def test_complete_pg_business_process_restarts_with_every_sqlite_connection_forbidden(pg_profiles):
    with pg_profiles("one") as first:
        prepare_workspace(first)
    with pg_profiles("two") as second:
        prepare_workspace(second)
    written = run("postgresql", "write", [first, second])
    recovered = run("postgresql", "read", [second, first])
    assert written["pid"] != recovered["pid"]
    assert written["sqlite_connections"] == recovered["sqlite_connections"] == 0
    assert not tuple(first.parent.glob("sqlite-attempt-*"))
