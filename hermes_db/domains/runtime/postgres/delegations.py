"""Owner delegation ledger with detached reads and short scoped writes."""

from contextlib import contextmanager
import json
import time

from sqlalchemy import case, func, or_, select

from hermes_db.domains.runtime.postgres.queries import delegations as repo
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.gateway import async_delegations as table
from hermes_state_runtime import RuntimeStoreError


class AsyncDelegationStore:
    def __init__(self, session_store):
        self._store = session_store

    @property
    def scope(self):
        return self._store.scope

    @contextmanager
    def _write(self):
        with self._store._profile.activate(), self._store._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            yield conn

    def dispatch(self, record, *, owner_pid, owner_started_at, task):
        values = dict(delegation_id=record["delegation_id"], origin_session=record.get("session_key", ""),
            origin_ui_session_id=record.get("origin_ui_session_id", ""), parent_session_id=record.get("parent_session_id"),
            state="running", dispatched_at=record["dispatched_at"], updated_at=time.time(), delivery_state="pending",
            delivery_attempts=0, owner_pid=owner_pid, owner_started_at=owner_started_at, task_json=json.dumps(task),
            origin_session_id=record.get("origin_session_id", ""))
        with self._write() as conn:
            # The owner path replaces its own scoped record; the worker path
            # uses the stricter assignment and receipt API.
            conn.execute(table.delete().where(repo.where(self.scope, record["delegation_id"])))
            repo.insert(conn, self.scope, values)

    def complete(self, event, result):
        with self._write() as conn:
            if repo.get(conn, self.scope, event["delegation_id"]) is None:
                raise RuntimeStoreError("not_found")
            now = time.time()
            repo.update(conn, self.scope, event["delegation_id"], {"state": event.get("status", "completed"),
                "completed_at": event.get("completed_at", now), "updated_at": now, "event_json": json.dumps(event),
                "result_json": json.dumps(result), "delivery_state": "pending"})

    def child(self, delegation_id, entry):
        with self._write() as conn:
            row = repo.get(conn, self.scope, delegation_id)
            if row is None or row["state"] != "running":
                return
            previous = json.loads(row["result_json"] or "{}")
            results = [item for item in previous.get("results") or [] if item.get("task_index") != entry.get("task_index")]
            repo.update(conn, self.scope, delegation_id, {"result_json": json.dumps({"results": [*results, entry], "partial": True}),
                                                         "updated_at": time.time()})

    def get(self, delegation_id):
        with self._store._read() as conn:
            row = repo.get(conn, self.scope, delegation_id)
        if row is None:
            return None
        columns = ("delegation_id", "origin_session", "state", "dispatched_at", "completed_at", "delivery_state", "delivery_attempts")
        return {key: row[key] for key in columns} | {"origin_session_id": row["origin_session_id"] or "",
            "result": json.loads(row["result_json"]) if row["result_json"] else None}

    def running_records(self):
        return self._records(table.c.state.in_(("running", "finalizing")))

    def pending_completions(self):
        return self._records(table.c.state != "running", table.c.delivery_state == "pending", table.c.event_json.is_not(None))

    def orphan_candidates(self, *, now, stale_seconds, lease_seconds):
        return self._records(table.c.state.not_in(("running", "finalizing")), table.c.delivery_state == "pending",
            table.c.event_json.is_not(None), table.c.updated_at < now - stale_seconds,
            or_(table.c.delivery_claim.is_(None), table.c.delivery_claimed_at < now - lease_seconds))

    def failed_records(self, *, origin_ui_session_id="", parent_session_id="", cutoff, limit=20):
        selectors = [column == value for column, value in ((table.c.origin_ui_session_id, origin_ui_session_id),
                                                          (table.c.parent_session_id, parent_session_id)) if value]
        if not selectors:
            return []
        columns = (table.c.delegation_id, table.c.state, table.c.dispatched_at, table.c.completed_at, table.c.task_json, table.c.result_json)
        with self._store._read() as conn:
            return list(conn.execute(select(*columns).where(table.c.store_id == self.scope.require_store_id(), or_(*selectors),
                table.c.state.not_in(("running", "finalizing")), table.c.completed_at >= cutoff)
                .order_by(table.c.completed_at.desc()).limit(limit)).tuples())

    def _records(self, *conditions):
        with self._store._read() as conn:
            rows = conn.execute(select(table).where(table.c.store_id == self.scope.require_store_id(), *conditions)
                .order_by(table.c.completed_at.asc().nullsfirst(), table.c.delegation_id)).mappings()
            return [{key: value for key, value in row.items() if key != "store_id"} for row in rows]

    def claim(self, delegation_id, claim_id, *, lease_seconds=300):
        now = time.time()
        with self._write() as conn:
            if repo.get(conn, self.scope, delegation_id) is None:
                raise RuntimeStoreError("not_found")
            return repo.update(conn, self.scope, delegation_id, {"delivery_claim": claim_id, "delivery_claimed_at": now,
                "delivery_attempts": table.c.delivery_attempts + 1, "updated_at": now}, table.c.delivery_state == "pending",
                or_(table.c.delivery_claim.is_(None), table.c.delivery_claimed_at < now - lease_seconds)) == 1

    def delivery(self, delegation_id, claim_id, action, *, attempt_cap):
        if action not in ("ack", "drop", "defer", "release"):
            raise ValueError("Unknown delivery action")
        with self._write() as conn:
            now = time.time()
            values = {"updated_at": now, "delivery_claim": None, "delivery_claimed_at": None}
            if action == "ack":
                values.update(delivery_state="delivered", delivered_at=now)
            elif action == "drop":
                values["delivery_state"] = "dropped"
            elif action == "defer":
                maximum = func.max if conn.dialect.name == "sqlite" else func.greatest
                values["delivery_attempts"] = maximum(0, table.c.delivery_attempts - 1)
            else:
                values["delivery_state"] = case((table.c.delivery_attempts >= attempt_cap, "dropped"), else_=table.c.delivery_state)
            return repo.update(conn, self.scope, delegation_id, values, table.c.delivery_state == "pending", table.c.delivery_claim == claim_id) == 1

    def mark_delivered(self, delegation_id):
        with self._write() as conn:
            now = time.time()
            return repo.update(conn, self.scope, delegation_id, {"delivery_state": "delivered", "delivered_at": now,
                "updated_at": now}, table.c.delivery_state != "delivered") == 1

    def recover_record(self, snapshot, event, result):
        """Liveness and transcript/git I/O precede this compare-and-swap."""
        fields = ("state", "updated_at", "owner_pid", "owner_started_at", "owner_execution_id", "result_json", "task_json", "event_json")
        with self._write() as conn:
            row = repo.get(conn, self.scope, snapshot["delegation_id"])
            if row is None or row["state"] not in ("running", "finalizing") or any(row[key] != snapshot[key] for key in fields):
                return False
            now = time.time()
            repo.update(conn, self.scope, row["delegation_id"], {"state": "unknown", "completed_at": now, "updated_at": now,
                "event_json": json.dumps(event), "result_json": json.dumps(result)})
            return True

    def drop_exhausted(self, delegation_id, *, now, attempt_cap, lease_seconds):
        with self._write() as conn:
            return repo.update(conn, self.scope, delegation_id, {"delivery_state": "dropped", "delivery_claim": None,
                "delivery_claimed_at": None, "updated_at": now}, table.c.delivery_state == "pending",
                table.c.delivery_attempts >= attempt_cap,
                or_(table.c.delivery_claim.is_(None), table.c.delivery_claimed_at < now - lease_seconds)) == 1

    def drop_expired(self, delegation_id, *, now, max_age_seconds):
        basis = func.coalesce(func.nullif(table.c.completed_at, 0), table.c.dispatched_at)
        with self._write() as conn:
            return repo.update(conn, self.scope, delegation_id, {"delivery_state": "dropped", "delivery_claim": None,
                "delivery_claimed_at": None, "updated_at": now}, table.c.delivery_state == "pending",
                basis != 0, basis < now - max_age_seconds) == 1

    def requeue_admitted(self, delegation_id, *, attempt_cap):
        with self._write() as conn:
            row = repo.get(conn, self.scope, delegation_id)
            if row is None or row["delivery_state"] != "delivered":
                return None
            now = time.time()
            if row["delivery_attempts"] >= attempt_cap:
                repo.update(conn, self.scope, delegation_id, {"delivery_state": "dropped", "updated_at": now})
                return None
            if row["event_json"] is None:
                return None
            values = {"delivery_state": "pending", "delivered_at": None, "updated_at": now}
            repo.update(conn, self.scope, delegation_id, values)
            return {**row, **values}

    def prune(self, *, retention_seconds, max_completed, max_pending):
        with self._write() as conn:
            own = table.c.store_id == self.scope.require_store_id()
            conn.execute(table.delete().where(own, table.c.delivery_state == "delivered", table.c.updated_at < time.time() - retention_seconds))
            terminal = [own, table.c.state.not_in(("running", "finalizing"))]
            _prune_overflow(conn, terminal, max_completed, prefer_delivered=True)
            _prune_overflow(conn, [*terminal, table.c.delivery_state == "pending"], max_pending)


def _prune_overflow(conn, conditions, maximum, *, prefer_delivered=False):
    count = conn.scalar(select(func.count()).select_from(table).where(*conditions))
    if count <= maximum:
        return
    order = [case((table.c.delivery_state == "delivered", 0), else_=1)] if prefer_delivered else []
    ids = select(table.c.delegation_id).where(*conditions).order_by(*order, table.c.updated_at, table.c.delegation_id).limit(count - maximum)
    conn.execute(table.delete().where(*conditions, table.c.delegation_id.in_(ids)))
