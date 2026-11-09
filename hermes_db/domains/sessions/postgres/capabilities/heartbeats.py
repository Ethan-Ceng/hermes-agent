"""Scoped process liveness and hygiene state; no host PID inference."""

import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.gateway import gateway_heartbeats as heartbeats, gateway_hygiene_state as hygiene


class SessionHeartbeats:
    def register_backend_heartbeat(self, *, backend_id, pid, started_at, last_heartbeat=None, profile="", host=""):
        with self._write() as conn:
            if not backend_id:
                return
            statement = insert(heartbeats).values(store_id=self.scope.require_store_id(), backend_id=str(backend_id),
                pid=int(pid), started_at=float(started_at), last_heartbeat=time.time() if last_heartbeat is None else float(last_heartbeat),
                profile=str(profile), host=str(host))
            fields = ("pid", "started_at", "last_heartbeat", "profile", "host")
            conn.execute(statement.on_conflict_do_update(index_elements=list(heartbeats.primary_key.columns),
                set_={field: statement.excluded[field] for field in fields}))

    def clear_backend_heartbeat(self, backend_id):
        with self._write() as conn:
            return bool(backend_id) and conn.execute(heartbeats.delete().where(
                heartbeats.c.store_id == self.scope.require_store_id(), heartbeats.c.backend_id == str(backend_id))).rowcount > 0

    def prune_stale_heartbeats(self, *, max_age_seconds):
        with self._write() as conn:
            if max_age_seconds <= 0:
                return []
            return list(conn.execute(heartbeats.delete().where(heartbeats.c.store_id == self.scope.require_store_id(),
                heartbeats.c.last_heartbeat < time.time() - max_age_seconds).returning(heartbeats.c.backend_id)).scalars())

    def list_backend_heartbeats(self):
        fields = ("backend_id", "pid", "started_at", "last_heartbeat", "profile", "host")
        with self._read() as conn:
            return [dict(row) for row in conn.execute(select(*(heartbeats.c[field] for field in fields))
                .where(heartbeats.c.store_id == self.scope.require_store_id()).order_by(heartbeats.c.last_heartbeat.desc())).mappings()]

    def increment_hygiene_failure_streak(self, session_key):
        with self._write() as conn:
            if not session_key:
                return 1
            statement = insert(hygiene).values(store_id=self.scope.require_store_id(), session_key=session_key, failure_streak=1)
            return conn.scalar(statement.on_conflict_do_update(index_elements=list(hygiene.primary_key.columns),
                set_={"failure_streak": hygiene.c.failure_streak + 1}).returning(hygiene.c.failure_streak))

    def reset_hygiene_failure_streak(self, session_key):
        with self._write() as conn:
            if session_key:
                conn.execute(hygiene.delete().where(hygiene.c.store_id == self.scope.require_store_id(), hygiene.c.session_key == session_key))
