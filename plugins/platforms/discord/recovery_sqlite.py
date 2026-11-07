"""Native SQLite ledger statements; respond is terminal across late dispatch transitions."""


def probe(conn):
    return conn.execute("SELECT 1").fetchone() is not None


def seen(conn, *, record):
    existing = conn.execute("SELECT status,updated_at FROM discord_messages WHERE message_id=?", (record["message_id"],)).fetchone()
    keep = bool(existing) and (existing[0] == "responded" or record["status"] == "discovered")
    row = dict(record)
    if keep:
        row.update(status=existing[0], updated_at=existing[1] or row["updated_at"])
    conn.execute("INSERT INTO discord_messages(message_id,channel_id,thread_id,parent_channel_id,author_id,created_at,status,updated_at) "
        "VALUES(:message_id,:channel_id,:thread_id,:parent_channel_id,:author_id,:created_at,:status,:updated_at) ON CONFLICT(message_id) DO UPDATE SET "
        "channel_id=excluded.channel_id,thread_id=excluded.thread_id,parent_channel_id=excluded.parent_channel_id,author_id=excluded.author_id,"
        "created_at=coalesce(discord_messages.created_at,excluded.created_at),status=excluded.status,updated_at=excluded.updated_at", row)


def attempt(conn, *, record, error):
    seen(conn, record=record)
    conn.execute("UPDATE discord_messages SET status=?,attempts=attempts+?,last_attempt_at=?,last_error=?,updated_at=? WHERE message_id=? AND status!='responded'",
        (record["status"], int(record["status"] == "queued"), record["updated_at"], error, record["updated_at"], record["message_id"]))


def processing_start(conn, *, record, message_id, emoji_ack, now):
    if record is not None:
        seen(conn, record=record)
    conn.execute("UPDATE discord_messages SET status='processing',emoji_ack=?,updated_at=? WHERE message_id=? AND status!='responded'", (int(emoji_ack), now, message_id))


def complete(conn, *, message_id, success, cancelled, now):
    if success:
        conn.execute("UPDATE discord_messages SET status='responded',replied=1,updated_at=? WHERE message_id=?", (now, message_id))
    else:
        conn.execute("UPDATE discord_messages SET status=CASE WHEN status='responded' THEN status ELSE ? END,updated_at=? WHERE message_id=?",
            ("cancelled" if cancelled else "failed", now, message_id))


def response(conn, *, message_id, response_id, completed, now):
    conn.execute("INSERT INTO discord_messages(message_id,status,replied,outage_response,response_message_id,updated_at) VALUES(?,?,?,0,?,?) "
        "ON CONFLICT(message_id) DO UPDATE SET status=CASE WHEN ? THEN 'responded' ELSE discord_messages.status END, "
        "replied=CASE WHEN ? THEN 1 ELSE discord_messages.replied END,outage_response=CASE WHEN ? THEN 0 ELSE discord_messages.outage_response END,"
        "response_message_id=coalesce(?,response_message_id),updated_at=?",
        (message_id, "responded" if completed else "failed", int(completed), response_id, now, completed, completed, completed, response_id, now))
    if completed:
        row = conn.execute("SELECT coalesce(thread_id,channel_id) FROM discord_messages WHERE message_id=?", (message_id,)).fetchone()
        if row and row[0]:
            advance_cursor(conn, channel_id=str(row[0]), message_id=message_id, now=now)


def is_complete(conn, *, message_id):
    row = conn.execute("SELECT status,replied,outage_response FROM discord_messages WHERE message_id=?", (message_id,)).fetchone()
    return bool(row and row[0] == "responded" and row[1] and not row[2])


def active_claim(conn, *, message_id, cutoff):
    row = conn.execute("SELECT status,updated_at FROM discord_messages WHERE message_id=?", (message_id,)).fetchone()
    return bool(row and row[0] in {"queued", "processing"} and row[1] >= cutoff)


def attempts_exhausted(conn, *, message_id, cap):
    row = conn.execute("SELECT attempts FROM discord_messages WHERE message_id=?", (message_id,)).fetchone()
    return bool(row and int(row[0] or 0) >= cap)


def scan_start(conn, *, record):
    conn.execute("INSERT INTO discord_recovery_scans(scan_id,started_at,status,channels,window_seconds,limit_count) "
        "VALUES(:scan_id,:started_at,:status,:channels,:window_seconds,:limit_count)", record)


def scan_complete(conn, *, record):
    conn.execute("UPDATE discord_recovery_scans SET completed_at=:completed_at,status=:status,scanned=:scanned,missed=:missed,"
        "dispatched=:dispatched,error=:error WHERE scan_id=:scan_id", record)


def cursor(conn, *, channel_id):
    row = conn.execute("SELECT last_message_id FROM discord_recovery_cursors WHERE channel_id=?", (channel_id,)).fetchone()
    return str(row[0]) if row else None


def advance_cursor(conn, *, channel_id, message_id, now):
    conn.execute("INSERT INTO discord_recovery_cursors(channel_id,last_message_id,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(channel_id) DO UPDATE SET last_message_id=excluded.last_message_id,updated_at=excluded.updated_at", (channel_id, message_id, now))
