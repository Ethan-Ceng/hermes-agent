"""Discord recovery writes serialize by owning store; delivered replies stay terminal."""

from sqlalchemy import delete, func, select, update
from hermes_db.domains.plugin_storage.discord.postgres.queries import recovery as repo
from hermes_db.tables.discord_recovery import messages, scans
from hermes_db.domains.plugin_storage.records.api import PluginRef
from hermes_db.domains.plugin_storage.records.postgres.operations import records as plugin_storage


def probe(conn, reference):
    return conn.scalar(select(1)) == 1


def seen(conn, reference, *, record):
    existing = repo.message(conn, reference, record["message_id"])
    row = dict(record)
    if existing is None:
        repo.insert_row(conn, reference, messages, row)
        return
    if existing["status"] == "responded" or row["status"] == "discovered":
        row.update(status=existing["status"], updated_at=existing["updated_at"] or row["updated_at"])
    row["created_at"] = existing["created_at"] if existing["created_at"] is not None else row["created_at"]
    conn.execute(update(messages).where(repo.identity(messages, reference, row["message_id"])).values(**repo.values(messages, row)))


def attempt(conn, reference, *, record, error):
    seen(conn, reference, record=record)
    conn.execute(update(messages).where(repo.identity(messages, reference, record["message_id"]), messages.c.status != "responded").values(
        status=record["status"], attempts=messages.c.attempts + int(record["status"] == "queued"), last_attempt_at=record["updated_at"],
        last_error=repo.values(messages, {"last_error": error})["last_error"], updated_at=record["updated_at"]))


def processing_start(conn, reference, *, record, message_id, emoji_ack, now):
    if record is not None:
        seen(conn, reference, record=record)
    conn.execute(update(messages).where(repo.identity(messages, reference, message_id), messages.c.status != "responded").values(status="processing", emoji_ack=int(emoji_ack), updated_at=now))


def complete(conn, reference, *, message_id, success, cancelled, now):
    row = repo.message(conn, reference, message_id)
    if row is None:
        return
    changes = dict(status="responded", replied=1, updated_at=now) if success else dict(
        status=row["status"] if row["status"] == "responded" else ("cancelled" if cancelled else "failed"), updated_at=now)
    conn.execute(update(messages).where(repo.identity(messages, reference, message_id)).values(**changes))


def response(conn, reference, *, message_id, response_id, completed, now):
    row = repo.message(conn, reference, message_id)
    if row is None:
        repo.insert_row(conn, reference, messages, dict(message_id=message_id, status="responded" if completed else "failed", replied=int(completed), response_message_id=response_id, updated_at=now))
        return
    changes = dict(response_message_id=response_id if response_id is not None else row["response_message_id"], updated_at=now)
    if completed:
        changes.update(status="responded", replied=1, outage_response=0)
    conn.execute(update(messages).where(repo.identity(messages, reference, message_id)).values(**repo.values(messages, changes)))
    channel = row["thread_id"] if row["thread_id"] is not None else row["channel_id"]
    if completed and channel:
        advance_cursor(conn, reference, channel_id=channel, message_id=message_id, now=now)


def is_complete(conn, reference, *, message_id):
    row = repo.message(conn, reference, message_id)
    return bool(row and row["status"] == "responded" and row["replied"] and not row["outage_response"])


def active_claim(conn, reference, *, message_id, cutoff):
    row = repo.message(conn, reference, message_id)
    return bool(row and row["status"] in {"queued", "processing"} and row["updated_at"] >= cutoff)


def attempts_exhausted(conn, reference, *, message_id, cap):
    row = repo.message(conn, reference, message_id)
    return bool(row and int(row["attempts"] or 0) >= cap)


def scan_start(conn, reference, *, record):
    repo.insert_row(conn, reference, scans, record)


def scan_complete(conn, reference, *, record):
    fields = {name: value for name, value in record.items() if name != "scan_id"}
    conn.execute(update(scans).where(repo.scope(scans, reference), scans.c.scan_id == record["scan_id"]).values(**repo.values(scans, fields)))


def _cursor_ref(reference):
    return PluginRef(reference.profile_home, reference.store_id, reference.target, reference.plugin_id, "recovery-cursors")


def cursor(conn, reference, *, channel_id):
    from plugins.plugin_storage_types import validate_key
    record = plugin_storage.get(conn, _cursor_ref(reference), validate_key(channel_id))
    return None if record is None else record.value


def advance_cursor(conn, reference, *, channel_id, message_id, now):
    from plugins.plugin_storage_types import encode_value, validate_key
    plugin_storage.put(conn, _cursor_ref(reference), validate_key(channel_id), encode_value(message_id), None, 30 * 24 * 3600)


def prune(conn, reference, *, cutoff):
    conn.execute(delete(messages).where(repo.scope(messages, reference), messages.c.updated_at < cutoff))
    conn.execute(delete(scans).where(repo.scope(scans, reference), func.coalesce(scans.c.completed_at, scans.c.started_at) < cutoff))
    plugin_storage.prune(conn, _cursor_ref(reference), 200)
