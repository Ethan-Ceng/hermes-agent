"""Actual backfill and restart use real PG state; external Discord traffic stays local."""

from types import SimpleNamespace
import pytest
from sqlalchemy import select
from gateway.config import PlatformConfig
from gateway.platforms.event import ProcessingOutcome
from hermes_db.domains.plugin_storage.discord.api import open_discord
from hermes_db.domains.plugin_storage.discord.postgres.queries.recovery import scope
from hermes_db.tables.discord_recovery import scans
from plugins.platforms.discord.adapter import DiscordAdapter
from tests.gateway.test_discord_missed_message_backfill import FakeChannel, make_message

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def adapter_for(monkeypatch):
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="local-test-token", extra={"missed_message_backfill": {"enabled": True, "channels": ["123"]}}))
    user = SimpleNamespace(id=999, bot=True)
    adapter._client = SimpleNamespace(user=user)
    monkeypatch.setattr(adapter, "_is_allowed_user", lambda *args, **kwargs: True)
    return adapter


@pytest.mark.asyncio
async def test_actual_backfill_scan_receipts_duplicate_suppression_and_reopen(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        adapter = adapter_for(monkeypatch)
        channel = FakeChannel(channel_id=123)
        message = make_message(message_id=9001, content="<@999> recover", channel=channel, mentions=[adapter._client.user])
        channel._history_messages = [message]
        adapter._client.get_channel = lambda channel_id: channel
        dispatched = []
        async def handle(received, **kwargs):
            dispatched.append(received.id)
            event = SimpleNamespace(raw_message=received, message_id=str(received.id))
            adapter._record_discord_processing_start(event, emoji_ack=True)
            adapter._record_discord_processing_complete(event, ProcessingOutcome.SUCCESS)
            return True
        adapter._handle_message = handle
        await adapter._run_missed_message_backfill()
        assert dispatched == [9001]
        restarted = adapter_for(monkeypatch)
        restarted._client.get_channel = lambda channel_id: channel
        restarted._handle_message = handle
        await restarted._run_missed_message_backfill()
        assert dispatched == [9001]
        with open_discord(adapter._discord_recovery_store.reference) as conn:
            history = conn.execute(select(scans).where(scope(scans, adapter._discord_recovery_store.reference))).mappings().all()
            assert len(history) == 2
            assert all(row["status"] == "success" for row in history)
            assert sorted(row["dispatched"] for row in history) == [0, 1]


@pytest.mark.asyncio
async def test_pg_failure_never_becomes_empty_recovery_or_successful_scan(pg_profiles, monkeypatch):
    from contextlib import contextmanager
    from hermes_db.domains.plugin_storage.discord.postgres import store as discord_recovery_store
    from hermes_db.errors import StorageUnavailableError
    with pg_profiles("one"):
        adapter = adapter_for(monkeypatch)
        assert adapter._discord_recovery_store.probe()
        @contextmanager
        def unavailable(*args, **kwargs):
            raise StorageUnavailableError("injected unavailable ledger")
            yield
        monkeypatch.setattr(discord_recovery_store, "open_discord", unavailable)
        with pytest.raises(StorageUnavailableError, match="unavailable ledger"):
            adapter._discord_message_is_persistently_complete("missing")
        with pytest.raises(StorageUnavailableError, match="unavailable ledger"):
            adapter._discord_message_has_active_claim("missing")
        with pytest.raises(StorageUnavailableError, match="unavailable ledger"):
            await adapter._run_missed_message_backfill()
