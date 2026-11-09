"""Viewer-close fences and narrow owner listing reads."""

import json

from sqlalchemy import select

from hermes_db.repositories import runtime
from hermes_db.domains.sessions.postgres.queries import session_queries, sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.runtime import session_admissions, state_meta, worker_executions
from hermes_db.core.values import decode_text
from hermes_state_mutation_retirement import VIEWER_CLOSE_PREFIX


def _policy_target(raw):
    if raw is None:
        return None
    record = json.loads(raw)
    entry = record.get('entry') if isinstance(record, dict) else None
    target = entry.get('session_id') if isinstance(entry, dict) else None
    return target if isinstance(target, str) else None


class RuntimeViewer:
    def viewer_busy(self, session_id, target):
        with self._store._read() as conn:
            queued = conn.scalar(select(session_admissions.c.admission_id).where(
                runtime.target_where(self.scope, session_id), session_admissions.c.status.in_(("queued", "started", "unknown"))).limit(1))
            worker = conn.scalar(select(worker_executions.c.execution_id).where(
                worker_executions.c.store_id == self.scope.require_store_id(), worker_executions.c.session_id.in_((session_id, target)),
                worker_executions.c.status.in_(("registered", "running", "unknown"))).limit(1))
            return queued is not None or worker is not None

    def store_viewer_close(self, *, epoch, session_id, record):
        with self._write() as conn:
            runtime.require_epoch(conn, self.scope, epoch)
            sessions.lock_store(conn, self.scope)
            runtime.set_meta(conn, self.scope, VIEWER_CLOSE_PREFIX + session_id, record)

    def forget_viewer_close(self, *, epoch, session_id, record):
        with self._write() as conn:
            runtime.require_epoch(conn, self.scope, epoch)
            sessions.lock_store(conn, self.scope)
            return conn.execute(state_meta.delete().where(state_meta.c.store_id == self.scope.require_store_id(),
                state_meta.c.key == VIEWER_CLOSE_PREFIX + session_id, state_meta.c.value == record)).rowcount > 0

    def session_last_active(self, session_id):
        with self._store._read() as conn:
            return conn.scalar(select(session_queries.last_activity(conn)).where(sessions.where_session(self.scope, session_id)))

    def live_store_facts(self, session_ids):
        from hermes_state_local import POLICY_PREFIX
        fields = ("id", "source", "title", "started_at", "ended_at", "message_count", "model", "hidden", "archived",
            "runtime_revision", "runtime_generation")
        with self._store._read() as conn:
            rows = [dict(row) for row in conn.execute(select(*[table.c[name] for name in fields]).where(
                table.c.store_id == self.scope.require_store_id(),
                table.c.id.in_(session_ids))).mappings()]
            receipts = conn.execute(select(state_meta.c.key, state_meta.c.value).where(
                state_meta.c.store_id == self.scope.require_store_id(),
                state_meta.c.key.in_([POLICY_PREFIX + row['id'] for row in rows])))
            targets = {key[len(POLICY_PREFIX):]: _policy_target(raw) for key, raw in receipts}
            ended = dict(conn.execute(select(table.c.id, table.c.ended_at).where(
                table.c.store_id == self.scope.require_store_id(),
                table.c.id.in_([target for target in targets.values() if target is not None]))).all())
            pending = conn.execute(select(session_admissions.c.target_session_id, session_admissions.c.admission_id,
                session_admissions.c.seq, session_admissions.c.status).where(session_admissions.c.store_id == self.scope.require_store_id(),
                session_admissions.c.target_session_id.in_(session_ids), session_admissions.c.status.in_(("queued", "started", "unknown")))
                .order_by(session_admissions.c.seq)).mappings().all()
        by_session = {}
        for row in rows:
            row["title"] = decode_text(row["title"])
            row['target_ended_at'] = ended.get(targets.get(row['id']))
        for row in pending:
            by_session.setdefault(row["target_session_id"], []).append(dict(row))
        return {row["id"]: row for row in rows}, by_session
