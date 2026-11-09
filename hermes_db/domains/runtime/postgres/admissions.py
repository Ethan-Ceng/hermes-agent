"""Explicit runtime admissions component borrowing the owner context; no pools or session facade."""
from hermes_db.domains.runtime.postgres.operations import api_binding, runtime as operations, runtime_queue
from sqlalchemy import select, func
from hermes_db.domains.runtime.postgres.queries import runtime as repo, runtime, terminal
from hermes_db.tables.runtime import session_admissions, runtime_epoch, session_admissions as admissions, worker_executions
import json
from hermes_db.domains.runtime.postgres.operations.runtime import _retired_replay
from hermes_db.domains.runtime.values import _json, _text, RuntimeStoreError
from hermes_state_keys import admission_fingerprint
import time
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.tables.conversations import sessions as table

def _webhook(payload, chat_id):
    native = json.loads(payload).get('native_text_v1')
    if not isinstance(native, dict) or native.get('automation') is not None:
        return False
    source = native.get('source')
    return isinstance(source, dict) and source.get('platform') == 'webhook' and (chat_id is None or source.get('chat_id') == chat_id)

class RuntimeAdmissions:

    def __init__(self, context):
        self._context = context

    def create_api_session(self, *, session_id, source, title, **values):
        from hermes_db.domains.sessions.postgres.operations import sessions as lifecycle, titles
        from hermes_db.domains.sessions.postgres.queries import sessions
        try:
            with self._context.write() as conn:
                sessions.lock_store(conn, self._context.scope, exclusive=True)
                if sessions.raw_session(conn, self._context.scope, session_id) is not None:
                    return (None, ('session_exists', 'Session already exists'))
                if sessions.retired_session(conn, self._context.scope, session_id):
                    return (None, ('session_deleted', 'Session was deleted; its id cannot be reused'))
                lifecycle.create_on_connection(conn, self._context.scope, session_id, source, own_profile=self._context.session.own_profile, **values)
                if title is not None:
                    titles.set_title_on_connection(conn, self._context.scope, session_id, str(title), 'user')
                    sessions.update_session(conn, self._context.scope, session_id, {'title_source': None})
                return (sessions.get_session(conn, self._context.scope, session_id), None)
        except ValueError as exc:
            return (None, f'title:{exc}')

    def queued_api_sessions(self):
        from sqlalchemy import select
        from hermes_db.tables.runtime import session_admissions as table
        with self._context.read() as conn:
            return list(conn.scalars(select(table.c.target_session_id).where(table.c.store_id == self._context.scope.require_store_id(), table.c.principal_id == 'api', table.c.status == 'queued').distinct()))

    def bind_api_session(self, **kwargs):
        with self._context.write() as conn:
            return api_binding.bind(conn, self._context.scope, own_profile=self._context.session.own_profile, **kwargs)

    def begin_epoch(self, *, instance_id):
        with self._context.write() as conn:
            return operations.begin_epoch(conn, self._context.scope, instance_id)

    def check_epoch(self, epoch):
        with self._context.read() as conn:
            repo.require_epoch(conn, self._context.scope, epoch)

    def current_epoch(self):
        from sqlalchemy import select
        from hermes_db.tables.runtime import runtime_epoch
        with self._context.read() as conn:
            return conn.scalar(select(runtime_epoch.c.epoch).where(runtime_epoch.c.store_id == self._context.scope.require_store_id(), runtime_epoch.c.singleton == 1))

    def admit_input(self, **kwargs):
        with self._context.write() as conn:
            return operations.admit(conn, self._context.scope, **kwargs)

    def claim_input(self, **kwargs):
        with self._context.write() as conn:
            return operations.claim(conn, self._context.scope, **kwargs)

    def settle_input(self, **kwargs):
        with self._context.write() as conn:
            return operations.settle(conn, self._context.scope, **kwargs)

    def cancel_input(self, **kwargs):
        with self._context.write() as conn:
            return operations.cancel(conn, self._context.scope, **kwargs)

    def steer_input(self, **kwargs):
        with self._context.write() as conn:
            return operations.steer(conn, self._context.scope, **kwargs)

    def revert_steer(self, **kwargs):
        with self._context.write() as conn:
            return operations.revert_steer(conn, self._context.scope, **kwargs)

    def recover_inputs(self, **kwargs):
        with self._context.write() as conn:
            return operations.recover(conn, self._context.scope, **kwargs)

    def resolve_unknown(self, **kwargs):
        with self._context.write() as conn:
            return operations.resolve_unknown(conn, self._context.scope, **kwargs)

    def mark_unknown(self, **kwargs):
        with self._context.write() as conn:
            return operations.mark_unknown(conn, self._context.scope, **kwargs)

    def rehome_inputs(self, **kwargs):
        with self._context.write() as conn:
            return runtime_queue.rehome(conn, self._context.scope, **kwargs)

    def retarget_automation(self, **kwargs):
        with self._context.write() as conn:
            return runtime_queue.retarget(conn, self._context.scope, **kwargs)

    def get_admission(self, *, admission_id):
        with self._context.read() as conn:
            return repo.public_row(repo.admission(conn, self._context.scope, admission_id))

    def find_admission(self, *, principal_id, session_id, request_id):
        with self._context.read() as conn:
            return repo.public_row(repo.find(conn, self._context.scope, principal_id, session_id, request_id))

    def list_admissions(self, *, session_id, pending_only=True):
        with self._context.read() as conn:
            conditions = [session_admissions.c.status.in_(('queued', 'started', 'unknown'))] if pending_only else []
            rows = conn.execute(select(session_admissions).where(repo.target_where(self._context.scope, session_id), *conditions).order_by(session_admissions.c.seq)).mappings()
            return [repo.public_row(row) for row in rows]

    def find_api_run(self, run_id, *, admission_id=None):
        from sqlalchemy import select
        from hermes_db.tables.runtime import session_admissions
        with self._context.read() as conn:
            if admission_id is not None:
                row = runtime.admission(conn, self._context.scope, admission_id)
                rows = [row] if row is not None and row['principal_id'] == 'api' else []
            else:
                rows = [dict(row) for row in conn.execute(select(session_admissions).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.principal_id == 'api', session_admissions.c.request_id == run_id)).mappings()]
                rows.extend(terminal.api_admissions(conn, self._context.scope, run_id))
        if len(rows) > 1:
            raise RuntimeStoreError('admission_conflict')
        return runtime.public_row(rows[0]) if rows else None

    def completion_replay(self, *, epoch, row):
        with self._context.read() as conn:
            runtime.require_epoch(conn, self._context.scope, epoch)
            current = runtime.admission(conn, self._context.scope, row['admission_id'])
            if current is None:
                raise RuntimeStoreError('not_found')
            if current['owner_epoch'] != epoch or current['generation'] != row['generation']:
                raise RuntimeStoreError('stale_generation')
            if current['status'] != 'terminal':
                return None
            saved = terminal.result(conn, self._context.scope, row['admission_id'])
            if saved is None:
                raise RuntimeStoreError('storage_unavailable')
            return (runtime.public_row(current), saved['result'].get('final_response') or '')

    def current_result(self, admission_id):
        with self._context.read() as conn:
            row = runtime.admission(conn, self._context.scope, admission_id)
            if row is None:
                raise RuntimeStoreError('not_found')
            return terminal.result(conn, self._context.scope, admission_id) if row['status'] == 'terminal' else None

    def retry_terminal_admission(self, *, epoch, principal_id, session_id, request_id, payload, intent='queue'):
        for value in (principal_id, session_id, request_id):
            _text(value)
        digest = admission_fingerprint(canonical_target=session_id, payload={'input': json.loads(_json(payload)), 'intent': intent})
        with self._context.read() as conn:
            runtime.require_epoch(conn, self._context.scope, epoch)
            return _retired_replay(conn, self._context.scope, principal_id, session_id, request_id, digest)

    def terminal_worker_receipt(self, **kwargs):
        with self._context.read() as conn:
            return terminal.worker_receipt(conn, self._context.scope, **kwargs)

    def terminal_api_admissions(self, request_id):
        with self._context.read() as conn:
            return terminal.api_admissions(conn, self._context.scope, request_id)

    def terminal_admission(self, admission_id):
        with self._context.read() as conn:
            return terminal.admission(conn, self._context.scope, admission_id)

    def admission_result(self, admission_id):
        with self._context.read() as conn:
            return terminal.result(conn, self._context.scope, admission_id)

    def pending_target_ids(self, statuses):
        with self._context.read() as conn:
            return set(conn.execute(select(admissions.c.target_session_id).where(admissions.c.store_id == self._context.scope.require_store_id(), admissions.c.status.in_(statuses))).scalars())

    def runtime_busy_reason(self):
        with self._context.read() as conn:
            if conn.scalar(select(admissions.c.admission_id).where(admissions.c.store_id == self._context.scope.require_store_id(), admissions.c.status.in_(('queued', 'started'))).limit(1)) is not None:
                return 'admissions pending'
            if conn.scalar(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == self._context.scope.require_store_id(), worker_executions.c.status != 'terminal').limit(1)) is not None:
                return 'managed worker live'

    def committed_delivery(self, principal, request_id):
        with self._context.read() as conn:
            return [dict(row) for row in conn.execute(select(admissions.c.admission_id).where(admissions.c.store_id == self._context.scope.require_store_id(), admissions.c.principal_id == principal, admissions.c.request_id == request_id)).mappings()]

    def webhook_payloads(self, chat_id):
        return [{'payload_json': row['payload_json']} for row in self._webhook_rows(chat_id=chat_id)]

    def webhook_finalizations(self):
        return [{'admission_id': row['admission_id']} for row in self._webhook_rows(finalizing=True)]

    def _webhook_rows(self, *, chat_id=None, finalizing=False):
        scoped = admissions.c.store_id == self._context.scope.require_store_id()
        query = select(admissions.c.seq, admissions.c.admission_id, admissions.c.payload_json).where(scoped)
        if finalizing:
            joined = admissions.join(table, (table.c.store_id == admissions.c.store_id) & (table.c.id == admissions.c.target_session_id))
            query = query.select_from(joined).where(table.c.source == 'webhook', table.c.ended_at.is_(None), admissions.c.status == 'terminal', admissions.c.generation.is_not(None))
        with self._context.read() as conn:
            ceiling = conn.scalar(select(func.max(admissions.c.seq)).where(scoped))
        cursor = 0
        while ceiling is not None and cursor < ceiling:
            with self._context.read() as conn:
                rows = conn.execute(query.where(admissions.c.seq > cursor, admissions.c.seq <= ceiling).order_by(admissions.c.seq).limit(128)).mappings().all()
            if not rows:
                break
            cursor = rows[-1]['seq']
            for row in rows:
                if _webhook(row['payload_json'], chat_id):
                    yield row

    def finalize_webhook(self, *, epoch, session_id, generation, admission_id, owner_epoch):
        with self._context.write() as conn:
            active = conn.scalar(select(runtime_epoch.c.epoch).where(runtime_epoch.c.store_id == self._context.scope.require_store_id(), runtime_epoch.c.singleton == 1).with_for_update())
            if active != epoch:
                return False
            sessions.lock_store(conn, self._context.scope, exclusive=True)
            target = sessions.lock_session(conn, self._context.scope, session_id)
            row = runtime.admission(conn, self._context.scope, admission_id)
            pending = conn.scalar(select(admissions.c.admission_id).where(admissions.c.store_id == self._context.scope.require_store_id(), admissions.c.target_session_id == session_id, admissions.c.status != 'terminal').limit(1))
            if target is None or target['ended_at'] is not None or target['runtime_generation'] != generation or (pending is not None) or (row is None) or ((row['target_session_id'], row['status'], row['generation'], row['owner_epoch']) != (session_id, 'terminal', generation, owner_epoch)):
                return False
            sessions.update_session(conn, self._context.scope, session_id, {'ended_at': time.time(), 'end_reason': 'webhook_complete'})
            sessions.bump_generation(conn, self._context.scope, target, 'webhook_complete')
            return True
