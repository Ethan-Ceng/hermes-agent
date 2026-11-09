"""Narrow scoped startup and webhook projections, never a database-file probe."""

import json
import time

from sqlalchemy import func, select

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.runtime import runtime_epoch, session_admissions as admissions, worker_executions


def _webhook(payload, chat_id):
    native = json.loads(payload).get('native_text_v1')
    if not isinstance(native, dict) or native.get('automation') is not None:
        return False
    source = native.get('source')
    return (isinstance(source, dict) and source.get('platform') == 'webhook'
        and (chat_id is None or source.get('chat_id') == chat_id))


class RuntimeRecovery:
    def pending_target_ids(self, statuses):
        with self._store._read() as conn:
            return set(conn.execute(select(admissions.c.target_session_id).where(
                admissions.c.store_id == self.scope.require_store_id(), admissions.c.status.in_(statuses))).scalars())

    def runtime_busy_reason(self):
        with self._store._read() as conn:
            if conn.scalar(select(admissions.c.admission_id).where(admissions.c.store_id == self.scope.require_store_id(),
                    admissions.c.status.in_(('queued', 'started'))).limit(1)) is not None:
                return 'admissions pending'
            if conn.scalar(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == self.scope.require_store_id(),
                    worker_executions.c.status != 'terminal').limit(1)) is not None:
                return 'managed worker live'

    def committed_delivery(self, principal, request_id):
        with self._store._read() as conn:
            return [dict(row) for row in conn.execute(select(admissions.c.admission_id).where(
                admissions.c.store_id == self.scope.require_store_id(), admissions.c.principal_id == principal,
                admissions.c.request_id == request_id)).mappings()]

    def webhook_payloads(self, chat_id):
        return [{'payload_json': row['payload_json']} for row in self._webhook_rows(chat_id=chat_id)]

    def webhook_finalizations(self):
        return [{'admission_id': row['admission_id']} for row in self._webhook_rows(finalizing=True)]

    def _webhook_rows(self, *, chat_id=None, finalizing=False):
        # PG JSON processing rejects NUL escapes even in unrelated body fields.
        # Parse detached, scoped batches; finalization rechecks its owner/root fences.
        scoped = admissions.c.store_id == self.scope.require_store_id()
        query = select(admissions.c.seq, admissions.c.admission_id, admissions.c.payload_json).where(scoped)
        if finalizing:
            joined = admissions.join(table, (table.c.store_id == admissions.c.store_id) &
                (table.c.id == admissions.c.target_session_id))
            query = query.select_from(joined).where(table.c.source == 'webhook', table.c.ended_at.is_(None),
                admissions.c.status == 'terminal', admissions.c.generation.is_not(None))
        with self._store._read() as conn:
            ceiling = conn.scalar(select(func.max(admissions.c.seq)).where(scoped))
        cursor = 0
        while ceiling is not None and cursor < ceiling:
            with self._store._read() as conn:
                rows = conn.execute(query.where(admissions.c.seq > cursor, admissions.c.seq <= ceiling)
                    .order_by(admissions.c.seq).limit(128)).mappings().all()
            if not rows:
                break
            cursor = rows[-1]['seq']
            for row in rows:
                if _webhook(row['payload_json'], chat_id):
                    yield row

    def finalize_webhook(self, *, epoch, session_id, generation, admission_id, owner_epoch):
        with self._write() as conn:
            active = conn.scalar(select(runtime_epoch.c.epoch).where(runtime_epoch.c.store_id == self.scope.require_store_id(),
                runtime_epoch.c.singleton == 1).with_for_update())
            if active != epoch:
                return False
            sessions.lock_store(conn, self.scope, exclusive=True)
            target = sessions.lock_session(conn, self.scope, session_id)
            row = runtime.admission(conn, self.scope, admission_id)
            pending = conn.scalar(select(admissions.c.admission_id).where(admissions.c.store_id == self.scope.require_store_id(),
                admissions.c.target_session_id == session_id, admissions.c.status != 'terminal').limit(1))
            if (target is None or target['ended_at'] is not None or target['runtime_generation'] != generation or pending is not None
                    or row is None or (row['target_session_id'], row['status'], row['generation'], row['owner_epoch']) !=
                    (session_id, 'terminal', generation, owner_epoch)):
                return False
            sessions.update_session(conn, self.scope, session_id, {'ended_at': time.time(), 'end_reason': 'webhook_complete'})
            sessions.bump_generation(conn, self.scope, target, 'webhook_complete')
            return True
