"""Managed tool helpers use closed authenticated owner reads rather than local stores."""

from types import SimpleNamespace

import pytest


def test_managed_tool_metadata_readers_never_open_a_database(monkeypatch):
    from tools.cronjob_tools import _run_session_usage
    from tools.kanban_tools import _persisted_session_id
    from tools.process_registry_results import _owns_result
    calls = []

    def read(operation, **payload):
        calls.append((operation, payload))
        return {"result.owns": True, "session.persisted": "working", "cron.usage": {"api_calls": 3, "model": "m"}}[operation]

    monkeypatch.setattr("agent.runtime_session_store.current_worker_store", lambda: SimpleNamespace(owner_read=read))
    monkeypatch.setattr("hermes_cli.db_sessions.open_session_store", lambda *args, **kwargs: pytest.fail("worker opened a database"))
    assert _owns_result("new-tip", "root")
    assert _persisted_session_id("working") == "working"
    assert _run_session_usage("job", "execution") == {"api_calls": 3, "model": "m"}
    assert [entry[0] for entry in calls] == ["result.owns", "session.persisted", "cron.usage"]
