"""Operational readers must observe their PG Profile rather than the existence of old files."""

import json
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def seed_message(home, *, tool_calls=None, tool_call_id=None, role="user", content="persisted"):
    from hermes_cli.db_setup import open_profile_db
    with open_profile_db(home) as handle:
        if handle.sessions.get_session("operational") is None:
            handle.sessions.create_session("operational", "cli")
        handle.sessions.append_message("operational", role, content, tool_calls=tool_calls, tool_call_id=tool_call_id)


def test_dirty_exit_and_readiness_probe_pg_without_inspecting_old_sqlite(pg_profiles):
    from gateway.lifecycle_ledger import check_state_db_integrity, run_deferred_integrity_check
    from gateway.readiness import _probe_state_db
    with pg_profiles("one") as home:
        seed_message(home)
        legacy = home / "state.db"
        legacy.write_bytes(b"legacy database must never be opened")
        assert check_state_db_integrity(home) == "ok"
        assert run_deferred_integrity_check({"prior_pid": 123}, home=home) == "ok"
        probe = _probe_state_db(home)
        assert probe["status"] == "ok" and probe["backend"] == "postgresql"
        assert legacy.read_bytes() == b"legacy database must never be opened"


def test_install_evidence_uses_scoped_pg_messages_without_state_file(pg_profiles):
    from hermes_cli.install_state import _Root, _messages
    with pg_profiles("one") as home:
        seed_message(home)
        assert not (home / "state.db").exists()
        assert _messages(_Root(home))
    with pg_profiles("two") as home:
        assert not _messages(_Root(home))


def test_approval_history_uses_pg_and_preserves_denial_and_profile_isolation(pg_profiles):
    from hermes_cli.approvals_suggest import scan_approval_history
    with pg_profiles("one") as home:
        for identity, command, result in (("approved", "git push --force origin main", "done"),
                ("denied", "git push --force origin topic", "BLOCKED: User denied")):
            calls = [{"id": identity, "type": "function", "function": {"name": "terminal", "arguments": json.dumps({"command": command})}}]
            seed_message(home, role="assistant", content="", tool_calls=calls)
            seed_message(home, role="tool", content=result, tool_call_id=identity)
        records = scan_approval_history(days=0)
        assert [command for command, _ in records] == ["git push --force origin main"]
        assert not (home / "state.db").exists()
    with pg_profiles("two"):
        assert scan_approval_history(days=0) == []
