"""Narrow scoped startup and webhook projections, never a database-file probe."""

import time

from sqlalchemy import select

from hermes_db.repositories import runtime, sessions
from hermes_db.repositories.session_queries import json_path_text, json_path_value
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.runtime import runtime_epoch, session_admissions as admissions, worker_executions


def _webhook(conn, scope):
    return (admissions.c.store_id == scope.require_store_id(),
        json_path_text(conn, admissions.c.payload_json, ('native_text_v1', 'source', 'platform')) == 'webhook',
        json_path_value(conn, admissions.c.payload_json, 'native_text_v1.automation').is_(None))


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
        with self._store._read() as conn:
            return [dict(row) for row in conn.execute(select(admissions.c.payload_json).where(*_webhook(conn, self.scope),
                json_path_text(conn, admissions.c.payload_json, ('native_text_v1', 'source', 'chat_id')) == chat_id)).mappings()]

    def webhook_finalizations(self):
        with self._store._read() as conn:
            joined = admissions.join(table, (table.c.store_id == admissions.c.store_id) &
                (table.c.id == admissions.c.target_session_id))
            return [dict(row) for row in conn.execute(select(admissions.c.admission_id).select_from(joined).where(
                *_webhook(conn, self.scope), table.c.source == 'webhook', table.c.ended_at.is_(None),
                admissions.c.status == 'terminal', admissions.c.generation.is_not(None))).mappings()]

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
