"""Actual PG Kanban worker protocol through the production embedded session runtime."""

import pytest

from tests.hermes_db.postgresql.scenarios.kanban_full_gateway import run_worker_probe

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize("separate_profile", [False, True])
def test_real_embedded_pg_owner_worker_and_tools_persist(pg_profiles, tmp_path, monkeypatch, separate_profile):
    run_worker_probe(pg_profiles, tmp_path, monkeypatch,
                     owner_module="tests.hermes_db.postgresql.scenarios.kanban_session_owner", separate_profile=separate_profile)
