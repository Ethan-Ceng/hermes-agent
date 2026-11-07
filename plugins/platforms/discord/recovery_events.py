"""Adapter events become ordinary records before entering bounded ledger operations."""

import datetime as dt
import json
import uuid
from gateway.platforms.event import ProcessingOutcome


def _record(adapter, message, status, now):
    message_id = str(getattr(message, "id", "") or "")
    if not message_id:
        return None
    channel_id, thread_id, parent_id = adapter._message_channel_ids(message)
    created_at = getattr(message, "created_at", None)
    return dict(message_id=message_id, channel_id=channel_id, thread_id=thread_id, parent_channel_id=parent_id,
        author_id=str(getattr(getattr(message, "author", None), "id", "") or ""),
        created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else None, status=status, updated_at=now)


def _error(error):
    from agent.redact import redact_sensitive_text
    return redact_sensitive_text(str(error), force=True, redact_url_credentials=True) if error else None


def seen(adapter, message, *, status):
    if not adapter._missed_message_backfill_enabled():
        return
    record = _record(adapter, message, status, adapter._utc_now_iso())
    if record is not None:
        adapter._discord_recovery_store.seen(record)


def attempt(adapter, message, *, status, error=None):
    if not adapter._missed_message_backfill_enabled():
        return
    record = _record(adapter, message, status, adapter._utc_now_iso())
    if record is not None:
        adapter._discord_recovery_store.attempt(record, error=_error(error))


def processing_start(adapter, event, *, emoji_ack):
    if not adapter._missed_message_backfill_enabled():
        return
    message_id = str(getattr(event.raw_message, "id", "") or getattr(event, "message_id", "") or "")
    if message_id:
        now = adapter._utc_now_iso()
        record = _record(adapter, event.raw_message, "processing", now)
        adapter._discord_recovery_store.processing_start(record, message_id=message_id, emoji_ack=emoji_ack, now=now)


def complete(adapter, event, outcome):
    if not adapter._missed_message_backfill_enabled():
        return
    message_id = str(getattr(getattr(event, "raw_message", None), "id", "") or getattr(event, "message_id", "") or "")
    if message_id:
        adapter._discord_recovery_store.complete(message_id, success=outcome == ProcessingOutcome.SUCCESS,
            cancelled=outcome == ProcessingOutcome.CANCELLED, now=adapter._utc_now_iso())


def response(adapter, *, reply_to, result, content, final):
    if adapter._missed_message_backfill_enabled() and reply_to:
        adapter._discord_recovery_store.response(reply_to, response_id=result.message_id,
            completed=bool(final and result.success), now=adapter._utc_now_iso())


def is_complete(adapter, message_id):
    return bool(message_id) and bool(adapter._discord_recovery_store.is_complete(message_id))


def active_claim(adapter, message_id):
    if not message_id:
        return False
    cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)).isoformat()
    return bool(adapter._discord_recovery_store.active_claim(message_id, cutoff=cutoff))


def exhausted(adapter, message_id):
    return bool(message_id) and bool(adapter._discord_recovery_store.attempts_exhausted(message_id, cap=adapter._missed_message_backfill_max_attempts()))


def scan_start(adapter, channels):
    scan_id = str(uuid.uuid4())
    adapter._discord_recovery_store.scan_start(dict(scan_id=scan_id, started_at=adapter._utc_now_iso(), status="running",
        channels=json.dumps(sorted(channels)), window_seconds=adapter._missed_message_backfill_window_seconds(), limit_count=adapter._missed_message_backfill_limit()))
    return scan_id


def scan_complete(adapter, scan_id, *, status, scanned, missed, dispatched, error=None):
    adapter._discord_recovery_store.scan_complete(dict(scan_id=scan_id, completed_at=adapter._utc_now_iso(), status=status,
        scanned=scanned, missed=missed, dispatched=dispatched, error=_error(error)))


def cursor(adapter, channel_id):
    return adapter._discord_recovery_store.cursor(channel_id) if channel_id else None


def advance_cursor(adapter, channel_id, message_id):
    if channel_id and message_id:
        adapter._discord_recovery_store.advance_cursor(channel_id, message_id=message_id, now=adapter._utc_now_iso())
