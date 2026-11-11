"""Actual Discord recovery entry points backed by scoped PG, never a SQLite connection."""

from types import SimpleNamespace
import pytest
from gateway.config import PlatformConfig
from gateway.platforms.event import ProcessingOutcome
from plugins.platforms.discord.adapter import DiscordAdapter
from tests.gateway.test_discord_missed_message_backfill import make_message

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def build_adapter(monkeypatch):
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="test-token"))
    monkeypatch.setattr(adapter, "_missed_message_backfill_enabled", lambda: True)
    return adapter


def test_completed_discord_message_reopens_and_late_attempt_cannot_uncomplete(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        adapter = build_adapter(monkeypatch)
        message = make_message(message_id=321)
        event = SimpleNamespace(raw_message=message, message_id="321")
        adapter._record_recovery_attempt(message, status="queued")
        adapter._record_discord_processing_start(event, emoji_ack=True)
        assert adapter._discord_message_has_active_claim("321")
        adapter._record_discord_processing_complete(event, ProcessingOutcome.SUCCESS)
        assert build_adapter(monkeypatch)._discord_message_is_persistently_complete("321")
        adapter._record_recovery_attempt(message, status="queued")
        adapter._record_discord_processing_complete(event, ProcessingOutcome.FAILURE)
        assert adapter._discord_message_is_persistently_complete("321")
    with pg_profiles("two"):
        assert not build_adapter(monkeypatch)._discord_message_is_persistently_complete("321")


def test_discord_response_carries_cursor_and_survives_reopen(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        adapter = build_adapter(monkeypatch)
        message = make_message(message_id=322)
        adapter._record_discord_message_seen(message, status="processing")
        adapter._record_discord_response(reply_to="322", result=SimpleNamespace(success=True, message_id="reply-322"), content="final body stays out of ledger", final=True)
        restarted = build_adapter(monkeypatch)
        assert restarted._discord_message_is_persistently_complete("322")
        assert restarted._discord_recovery_cursor("123") == "322"


def test_pg_claim_age_and_attempt_budget_survive_discovery(pg_profiles, monkeypatch):
    from datetime import datetime, timedelta, UTC
    from sqlalchemy import update
    from plugins.plugin_storage import open_discord
    from hermes_db.domains.plugin_storage.discord.postgres.queries import recovery as repo
    from hermes_db.tables.discord_recovery import messages
    with pg_profiles("one"):
        adapter = build_adapter(monkeypatch)
        monkeypatch.setattr(adapter, "_missed_message_backfill_max_attempts", lambda: 2)
        message = make_message(message_id=321)
        adapter._record_recovery_attempt(message, status="queued")
        assert adapter._discord_message_has_active_claim("321")
        assert not adapter._discord_message_attempts_exhausted("321")
        reference = adapter._discord_recovery_store.reference
        expired = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        with open_discord(reference, write=True) as conn:
            conn.execute(update(messages).where(repo.identity(messages, reference, "321")).values(updated_at=expired))
        adapter._record_discord_message_seen(message, status="discovered")
        assert not adapter._discord_message_has_active_claim("321")
        adapter._record_recovery_attempt(message, status="queued")
        assert adapter._discord_message_attempts_exhausted("321")
        assert adapter._discord_message_has_active_claim("321")


def test_pg_private_sqlite_callbacks_are_explicitly_refused(pg_profiles, monkeypatch):
    from hermes_db.errors import StorageConfigurationError
    with pg_profiles("one"):
        adapter = build_adapter(monkeypatch)
        with pytest.raises(StorageConfigurationError, match="named operations"):
            adapter._with_discord_recovery_db(lambda conn: None)


def test_opaque_ids_empty_values_and_null_coalesce_match_native_contract(pg_profiles, monkeypatch):
    from plugins.plugin_storage import open_discord
    from hermes_db.domains.plugin_storage.discord.postgres.queries.recovery import message
    with pg_profiles("one"):
        store = build_adapter(monkeypatch)._discord_recovery_store
        stamp = "2026-11-08T00:00:00+00:00"
        record = dict(message_id="opaque\x00🙂", channel_id="channel", thread_id="", parent_channel_id=None,
            author_id="author\x00🙂", created_at="", status="processing", updated_at=stamp)
        store.seen(record)
        store.seen(dict(record, created_at=stamp))
        store.response(record["message_id"], response_id="reply\x00🙂", completed=True, now=stamp)
        assert store.is_complete(record["message_id"])
        assert store.cursor("channel") is None
        with open_discord(store.reference) as conn:
            current = message(conn, store.reference, record["message_id"])
            assert current["created_at"] == "" and current["thread_id"] == ""
            assert current["author_id"] == record["author_id"] and current["response_message_id"] == "reply\x00🙂"
