"""A late recovery dispatch cannot undo a delivered final (intent: 8c6881231a)."""

from types import SimpleNamespace
from gateway.config import PlatformConfig
from gateway.platforms.event import ProcessingOutcome
from plugins.platforms.discord.adapter import DiscordAdapter
from tests.gateway.test_discord_missed_message_backfill import make_message


def test_late_recovery_attempt_keeps_completed_message_terminal(monkeypatch):
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="test-token"))
    monkeypatch.setattr(adapter, "_missed_message_backfill_enabled", lambda: True)
    message = make_message(message_id=321)
    event = SimpleNamespace(raw_message=message, message_id="321")
    adapter._record_recovery_attempt(message, status="queued")
    adapter._record_discord_processing_complete(event, ProcessingOutcome.SUCCESS)
    assert adapter._discord_message_is_persistently_complete("321")
    adapter._record_recovery_attempt(message, status="queued")
    assert adapter._discord_message_is_persistently_complete("321")
