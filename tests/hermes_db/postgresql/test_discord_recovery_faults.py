"""Atomic reply/cursor persistence, unknown commits, retention and error handling."""

from contextlib import contextmanager
from datetime import datetime, timedelta, UTC
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from sqlalchemy import select, update
from hermes_db.domains.plugin_storage.discord.api import open_discord
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.plugin_storage.discord.postgres.queries import recovery as repo
from hermes_db.tables.discord_recovery import messages, scans
from tests.hermes_db.postgresql.test_discord_recovery import build_adapter
from tests.gateway.test_discord_missed_message_backfill import make_message

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_response_and_portable_cursor_roll_back_together(pg_profiles, monkeypatch):
    from hermes_db.domains.plugin_storage.records.postgres.operations import records as plugin_storage
    with pg_profiles("one"):
        adapter = build_adapter(monkeypatch)
        adapter._record_discord_message_seen(make_message(message_id=322), status="processing")
        original = plugin_storage.put
        def refuse(*args, **kwargs):
            raise RuntimeError("injected cursor write refusal")
        monkeypatch.setattr(plugin_storage, "put", refuse)
        with pytest.raises(RuntimeError, match="cursor write refusal"):
            adapter._record_discord_response(reply_to="322", result=SimpleNamespace(success=True, message_id="reply"), content="done", final=True)
        assert not adapter._discord_message_is_persistently_complete("322")
        assert adapter._discord_recovery_cursor("123") is None
        monkeypatch.setattr(plugin_storage, "put", original)
        adapter._record_discord_response(reply_to="322", result=SimpleNamespace(success=True, message_id="reply"), content="done", final=True)
        assert adapter._discord_message_is_persistently_complete("322")
        assert adapter._discord_recovery_cursor("123") == "322"


def test_actual_commit_missing_ack_recovers_receipt_and_cursor_in_new_process(pg_profiles, monkeypatch):
    from hermes_db.domains.plugin_storage.discord.postgres import store as discord_recovery_store
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        adapter = build_adapter(monkeypatch)
        adapter._record_discord_message_seen(make_message(message_id=322), status="processing")
        original = discord_recovery_store.open_discord
        @contextmanager
        def lost_ack(*args, **kwargs):
            with original(*args, **kwargs) as conn:
                yield conn
            if kwargs.get("write"):
                raise UnknownCommitError("injected confirmation loss after actual response COMMIT")
        monkeypatch.setattr(discord_recovery_store, "open_discord", lost_ack)
        with pytest.raises(UnknownCommitError):
            adapter._record_discord_response(reply_to="322", result=SimpleNamespace(success=True, message_id="reply"), content="done", final=True)
        monkeypatch.setattr(discord_recovery_store, "open_discord", original)
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
        script = Path(__file__).with_name("scenarios") / "discord_recovery.py"
        child = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert child.returncode == 0, child.stderr
        assert "PG_DISCORD_RESTART_RECEIPT_OK" in child.stdout


def test_retention_and_error_redaction_use_actual_scoped_records(pg_profiles, monkeypatch):
    from plugins.platforms.discord.recovery import DiscordRecoveryStore
    with pg_profiles("one"):
        adapter = build_adapter(monkeypatch)
        adapter._record_recovery_attempt(make_message(message_id=333), status="failed",
            error="postgresql://user:never-a-real-password@localhost/test?password=fake-secret")
        first_scan = adapter._record_recovery_scan_start({"123"})
        adapter._record_recovery_scan_complete(first_scan, status="failed", scanned=1, missed=1, dispatched=0, error="password=fake-secret")
        reference = adapter._discord_recovery_store.reference
        with open_discord(reference) as conn:
            row = repo.message(conn, reference, "333")
            assert "never-a-real-password" not in row["last_error"] and "fake-secret" not in row["last_error"]
        cutoff = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with open_discord(reference, write=True) as conn:
            conn.execute(update(messages).where(repo.identity(messages, reference, "333")).values(updated_at=cutoff))
            conn.execute(update(scans).where(repo.scope(scans, reference), scans.c.scan_id == first_scan).values(started_at=cutoff, completed_at=cutoff))
        assert DiscordRecoveryStore().probe()
        with open_discord(reference) as conn:
            assert repo.message(conn, reference, "333") is None
            assert conn.scalar(select(scans.c.scan_id).where(repo.scope(scans, reference), scans.c.scan_id == first_scan)) is None


def test_one_profile_retention_never_prunes_another_profiles_old_rows(pg_profiles, monkeypatch):
    from plugins.platforms.discord.recovery import DiscordRecoveryStore
    cutoff = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    references = {}
    for name in ("one", "two"):
        with pg_profiles(name):
            adapter = build_adapter(monkeypatch)
            adapter._record_discord_message_seen(make_message(message_id=333), status="processing")
            references[name] = adapter._discord_recovery_store.reference
            with open_discord(references[name], write=True) as conn:
                conn.execute(update(messages).where(repo.identity(messages, references[name], "333")).values(updated_at=cutoff))
    with pg_profiles("one"):
        assert DiscordRecoveryStore().probe()
    with open_discord(references["one"]) as conn:
        assert repo.message(conn, references["one"], "333") is None
    with open_discord(references["two"]) as conn:
        assert repo.message(conn, references["two"], "333") is not None
