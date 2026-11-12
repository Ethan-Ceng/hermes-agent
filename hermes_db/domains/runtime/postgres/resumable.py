"""Scoped resumable records in the existing state_meta dataset; no private SQLite or implicit DDL."""
import json
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.runtime import state_meta

_PREFIX = "delegation.resumable.v1:"
_END = "delegation.resumable.v1;"


class PostgresResumableLedger:
    def __init__(self, connection, scope, target):
        self.connection = connection
        self.store_id = scope.require_store_id()
        # Serialize this small namespace, including first inserts and pruning, across processes.
        connection.execute(select(func.pg_advisory_xact_lock(
            func.hashtextextended(target + ":" + self.store_id + ":resumable_subagents", 0))))

    def _where(self, sid):
        return (state_meta.c.store_id == self.store_id) & (state_meta.c.key == _PREFIX + sid)

    def _load(self, sid):
        raw = self.connection.scalar(select(state_meta.c.value).where(self._where(sid)))
        return json.loads(raw) if raw is not None else None

    def _put(self, sid, value):
        statement = insert(state_meta).values(store_id=self.store_id, key=_PREFIX + sid,
                                             value=json.dumps(value, ensure_ascii=False, default=str))
        self.connection.execute(statement.on_conflict_do_update(
            index_elements=[state_meta.c.store_id, state_meta.c.key], set_={"value": statement.excluded.value}))

    def _rows(self):
        rows = self.connection.execute(select(state_meta.c.key, state_meta.c.value).where(
            state_meta.c.store_id == self.store_id, state_meta.c.key >= _PREFIX, state_meta.c.key < _END))
        return [(key[len(_PREFIX):], json.loads(raw)) for key, raw in rows]

    def record(self, sid):
        row = self._load(sid)
        if row is None:
            return None
        return {**row["record"], **{key: row.get(key) for key in (
            "state", "stop_cause", "owner_pid", "owner_started_at")}}

    def save(self, sid, record, *, state, pinned, expires_at, stop_cause, now):
        previous = self._load(sid)
        value = {"record": {key: value for key, value in record.items() if key not in ("state", "stop_cause")},
                 "state": state, "pinned": bool(pinned), "expires_at": expires_at, "stop_cause": stop_cause,
                 "owner_pid": record.get("owner_pid"), "owner_started_at": record.get("owner_started_at"),
                 "created_at": previous["created_at"] if previous is not None else now, "updated_at": now}
        self._put(sid, value)

    def prune(self, *, now, expired_before, cap):
        pinned = []
        for sid, row in self._rows():
            if row["expires_at"] is not None and row["expires_at"] <= now and row["state"] in (
                    "resumable", "completed", "stopped"):
                row.update(pinned=False, state="expired")
                self._put(sid, row)
            if row["state"] == "expired" and row["updated_at"] < expired_before:
                self.connection.execute(delete(state_meta).where(self._where(sid)))
            elif row["pinned"]:
                pinned.append((sid, row))
        pinned.sort(key=lambda item: item[1]["updated_at"], reverse=True)
        for sid, row in pinned[cap:]:
            row["pinned"] = False
            self._put(sid, row)

    def checkpoint(self, sid, cwd, baselines, now):
        row = self._load(sid)
        if row is not None and row["state"] == "running":
            row["record"].update(cwd=cwd, repo_baselines=baselines)
            row["updated_at"] = now
            self._put(sid, row)

    def mark_shutdown(self, pid, cause):
        count = 0
        for sid, row in self._rows():
            if row["state"] == "running" and row["owner_pid"] == pid:
                row["stop_cause"] = cause
                self._put(sid, row)
                count += 1
        return count

    def running(self):
        return [(sid, row["owner_pid"], row["owner_started_at"], json.dumps(row["record"]))
                for sid, row in self._rows() if row["state"] in ("running", "claimed")]

    def owner(self, sid):
        row = self._load(sid)
        return (row["state"], row["owner_pid"], row["owner_started_at"]) if row is not None else None

    def claim(self, sid, state, owner, now):
        row = self._load(sid)
        if row is None or row["state"] != state:
            return 0
        row.update(state="claimed", owner_pid=owner["owner_pid"],
                   owner_started_at=owner["owner_started_at"], updated_at=now)
        self._put(sid, row)
        return 1

    def release(self, sid, state, owner_pid=None):
        row = self._load(sid)
        if (row is None or row["state"] != "claimed"
                or (owner_pid is not None and row["owner_pid"] != owner_pid)):
            return 0
        row["state"] = state
        self._put(sid, row)
        return 1

    def pins(self, now, cap):
        rows = [(sid, row) for sid, row in self._rows() if row["pinned"]
                and row["state"] in ("resumable", "running", "claimed")
                and (row["expires_at"] is None or row["expires_at"] > now)]
        rows.sort(key=lambda item: item[1]["updated_at"], reverse=True)
        return [(sid, json.dumps(row["record"]), row["expires_at"], row["state"]) for sid, row in rows[:cap]]
