"""New-interpreter Discord ledger recovery; SQLite is rejected including aliases and URI."""

import sqlite3
import sys
from datetime import datetime, UTC

attempts = []


def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("SQLite rejected in PG Discord recovery process")


sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == "sqlite3.connect" else None)
from plugins.platforms.discord.recovery import DiscordRecoveryStore

store = DiscordRecoveryStore()
assert store.probe()
role = sys.argv[1] if len(sys.argv) > 1 else "read"
if role in {"attempt", "response"}:
    sys.stdin.readline()
    stamp = datetime.now(UTC).isoformat()
    if role == "attempt":
        store.attempt(dict(message_id="322", channel_id="123", thread_id=None, parent_channel_id=None, author_id="42", created_at=stamp, status="queued", updated_at=stamp), error=None)
    else:
        store.response("322", response_id="reply-322", completed=True, now=stamp)
    print("PG_DISCORD_TRANSITION_OK")
else:
    assert store.is_complete("322")
    assert store.cursor("123") == "322"
    print("PG_DISCORD_RESTART_RECEIPT_OK")
assert not attempts
