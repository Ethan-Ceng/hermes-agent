"""Separate processes race late dispatch against the delivered-response transaction."""

from pathlib import Path
import subprocess
import sys
import pytest
from tests.gateway.test_discord_missed_message_backfill import make_message
from tests.hermes_db.postgresql.test_discord_recovery import build_adapter

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_separate_processes_cannot_undo_response_or_lose_its_cursor(pg_profiles, monkeypatch):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        adapter = build_adapter(monkeypatch)
        adapter._record_discord_message_seen(make_message(message_id=322), status="processing")
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
        script = Path(__file__).with_name("scenarios") / "discord_recovery.py"
        children = [subprocess.Popen([sys.executable, str(script), role], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8") for role in ("attempt", "response")]
        try:
            for child in children:
                child.stdin.write("go\n")
                child.stdin.flush()
            results = [child.communicate(timeout=60) for child in children]
            assert all(child.returncode == 0 for child in children), [stderr for _, stderr in results]
            assert all("PG_DISCORD_TRANSITION_OK" in stdout for stdout, _ in results)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
        assert build_adapter(monkeypatch)._discord_message_is_persistently_complete("322")
        assert build_adapter(monkeypatch)._discord_recovery_cursor("123") == "322"
