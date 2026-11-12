"""Named native resumable-delegation record operations; the application owns the connection."""
import json
import sqlite3


def ledger(connection):
    return SqliteResumableLedger(connection) if isinstance(connection, sqlite3.Connection) else connection


class SqliteResumableLedger:
    def __init__(self, connection):
        self.connection = connection

    def record(self, sid):
        row = self.connection.execute(
            "SELECT record_json, state, stop_cause, owner_pid, owner_started_at FROM resumable_subagents "
            "WHERE subagent_id=?", (sid,)).fetchone()
        if row is None:
            return None
        return {**json.loads(row[0] or "{}"), "state": row[1], "stop_cause": row[2],
                "owner_pid": row[3], "owner_started_at": row[4]}

    def save(self, sid, record, *, state, pinned, expires_at, stop_cause, now):
        record = {key: value for key, value in record.items() if key not in ("state", "stop_cause")}
        self.connection.execute(
            """INSERT INTO resumable_subagents (subagent_id, state, pinned, stop_cause, owner_pid, owner_started_at,
                   record_json, created_at, updated_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(subagent_id) DO UPDATE SET state=excluded.state, pinned=excluded.pinned,
                   stop_cause=excluded.stop_cause, owner_pid=excluded.owner_pid,
                   owner_started_at=excluded.owner_started_at, record_json=excluded.record_json,
                   updated_at=excluded.updated_at, expires_at=excluded.expires_at""",
            (sid, state, int(pinned), stop_cause, record.get("owner_pid"), record.get("owner_started_at"),
             json.dumps(record, ensure_ascii=False, default=str), now, now, expires_at))

    def prune(self, *, now, expired_before, cap):
        self.connection.execute("UPDATE resumable_subagents SET pinned=0, state='expired' WHERE expires_at IS NOT NULL "
                                "AND expires_at <= ? AND state IN ('resumable','completed','stopped')", (now,))
        self.connection.execute("DELETE FROM resumable_subagents WHERE state='expired' AND updated_at < ?",
                                (expired_before,))
        self.connection.execute("""UPDATE resumable_subagents SET pinned=0 WHERE pinned=1 AND subagent_id NOT IN (
                                SELECT subagent_id FROM resumable_subagents WHERE pinned=1
                                ORDER BY updated_at DESC LIMIT ?)""", (cap,))

    def checkpoint(self, sid, cwd, baselines, now):
        self.connection.execute("UPDATE resumable_subagents SET record_json=json_set(record_json, '$.cwd', ?, "
                                "'$.repo_baselines', json(?)), updated_at=? WHERE subagent_id=? AND state='running'",
                                (cwd, json.dumps(baselines), now, sid))

    def mark_shutdown(self, pid, cause):
        return self.connection.execute("UPDATE resumable_subagents SET stop_cause=? WHERE state='running' "
                                       "AND owner_pid=?", (cause, pid)).rowcount

    def running(self):
        return self.connection.execute("SELECT subagent_id, owner_pid, owner_started_at, record_json "
                                       "FROM resumable_subagents WHERE state IN ('running','claimed')").fetchall()

    def owner(self, sid):
        return self.connection.execute("SELECT state, owner_pid, owner_started_at FROM resumable_subagents "
                                       "WHERE subagent_id=?", (sid,)).fetchone()

    def claim(self, sid, state, owner, now):
        return self.connection.execute("UPDATE resumable_subagents SET state='claimed', owner_pid=?, "
                                       "owner_started_at=?, updated_at=? WHERE subagent_id=? AND state=?",
                                       (owner["owner_pid"], owner["owner_started_at"], now, sid, state)).rowcount

    def release(self, sid, state, owner_pid=None):
        query = "UPDATE resumable_subagents SET state=? WHERE subagent_id=? AND state='claimed'"
        args = (state, sid)
        if owner_pid is not None:
            query += " AND owner_pid=?"
            args += (owner_pid,)
        return self.connection.execute(query, args).rowcount

    def pins(self, now, cap):
        return self.connection.execute("SELECT subagent_id, record_json, expires_at, state FROM resumable_subagents "
            "WHERE pinned=1 AND state IN ('resumable','running','claimed') "
            "AND (expires_at IS NULL OR expires_at > ?) ORDER BY updated_at DESC LIMIT ?", (now, cap)).fetchall()
