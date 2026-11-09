"""Explicit runtime policy component borrowing the owner context; no pools or session facade."""
from hermes_db.domains.runtime.postgres.operations import deferred_pick
from sqlalchemy import select
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.runtime import session_admissions, state_meta, worker_executions
from hermes_db.domains.sessions.postgres.queries import bot_views, session_queries, sessions
import json
from hermes_db.tables.conversations import sessions as table
from hermes_db.core.values import decode_text
from hermes_db.domains.runtime.receipts import VIEWER_CLOSE_PREFIX

def _policy_target(raw):
    if raw is None:
        return None
    record = json.loads(raw)
    entry = record.get('entry') if isinstance(record, dict) else None
    target = entry.get('session_id') if isinstance(entry, dict) else None
    return target if isinstance(target, str) else None

class RuntimePolicy:

    def __init__(self, context):
        self._context = context

    def defer_pick(self, **kwargs):
        with self._context.write() as conn:
            return deferred_pick.defer(conn, self._context.scope, **kwargs)

    def compare_deferred_pick(self, **kwargs):
        with self._context.write() as conn:
            return deferred_pick.compare(conn, self._context.scope, **kwargs)

    def mutate_session(self, **kwargs):
        from hermes_db.domains.sessions.postgres.operations.mutations import mutate
        with self._context.write() as conn:
            result, event = mutate(conn, self._context.scope, ownership=self._context.session.ownership, routes=self._context.session.routes, **kwargs, media_references=self._context.session.media.admission_references)
        if event is not None:
            self._context.session.effects.deleted(event[0], reason=event[1], primary=kwargs['session_id'])
            if event[1] == 'delete':
                self._context.collect_retired_media()
        return result

    def policy_picks(self, session_id):
        from hermes_db.domains.sessions.postgres.operations.mutation_policy import picks
        with self._context.read() as conn:
            return picks(conn, self._context.scope, session_id)

    def commit_refreshed_policy(self, **kwargs):
        from hermes_db.domains.sessions.postgres.operations.mutation_policy import refresh
        with self._context.write() as conn:
            return refresh(conn, self._context.scope, **kwargs)

    def prepare_chat_pick(self, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.chat_pick import prepare
        with self._context.read() as conn:
            return prepare(conn, self._context.scope, **kwargs)

    def commit_chat_pick(self, **kwargs):
        from hermes_db.domains.runtime.postgres.operations.chat_pick import commit
        with self._context.write() as conn:
            return commit(conn, self._context.scope, **kwargs)

    def request_admission_id(self, session_id, request_id):
        with self._context.read() as conn:
            return conn.scalar(select(session_admissions.c.admission_id).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.target_session_id == session_id, session_admissions.c.request_id == request_id).limit(1))

    def has_request(self, request_id, *, session_id=None):
        with self._context.read() as conn:
            query = select(session_admissions.c.admission_id).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.request_id == request_id)
            if session_id is not None:
                query = query.where(session_admissions.c.target_session_id == session_id)
            return conn.scalar(query.limit(1)) is not None

    def holds_admissions(self, session_ids):
        with self._context.read() as conn:
            return conn.scalar(select(session_admissions.c.admission_id).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.target_session_id.in_(session_ids)).limit(1)) is not None

    def bot_sessions(self, subject, operator):
        with self._context.read() as conn:
            return bot_views.roster(conn, self._context.scope, subject, operator, same_owner=self._context.session.ownership.same_owner)

    def viewer_busy(self, session_id, target):
        with self._context.read() as conn:
            queued = conn.scalar(select(session_admissions.c.admission_id).where(runtime.target_where(self._context.scope, session_id), session_admissions.c.status.in_(('queued', 'started', 'unknown'))).limit(1))
            worker = conn.scalar(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == self._context.scope.require_store_id(), worker_executions.c.session_id.in_((session_id, target)), worker_executions.c.status.in_(('registered', 'running', 'unknown'))).limit(1))
            return queued is not None or worker is not None

    def store_viewer_close(self, *, epoch, session_id, record):
        with self._context.write() as conn:
            runtime.require_epoch(conn, self._context.scope, epoch)
            sessions.lock_store(conn, self._context.scope)
            runtime.set_meta(conn, self._context.scope, VIEWER_CLOSE_PREFIX + session_id, record)

    def forget_viewer_close(self, *, epoch, session_id, record):
        with self._context.write() as conn:
            runtime.require_epoch(conn, self._context.scope, epoch)
            sessions.lock_store(conn, self._context.scope)
            return conn.execute(state_meta.delete().where(state_meta.c.store_id == self._context.scope.require_store_id(), state_meta.c.key == VIEWER_CLOSE_PREFIX + session_id, state_meta.c.value == record)).rowcount > 0

    def session_last_active(self, session_id):
        with self._context.read() as conn:
            return conn.scalar(select(session_queries.last_activity(conn)).where(sessions.where_session(self._context.scope, session_id)))

    def live_store_facts(self, session_ids):
        from hermes_db.domains.runtime.receipts import POLICY_PREFIX
        fields = ('id', 'source', 'title', 'started_at', 'ended_at', 'message_count', 'model', 'hidden', 'archived', 'runtime_revision', 'runtime_generation')
        with self._context.read() as conn:
            rows = [dict(row) for row in conn.execute(select(*[table.c[name] for name in fields]).where(table.c.store_id == self._context.scope.require_store_id(), table.c.id.in_(session_ids))).mappings()]
            receipts = conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == self._context.scope.require_store_id(), state_meta.c.key.in_([POLICY_PREFIX + row['id'] for row in rows])))
            targets = {key[len(POLICY_PREFIX):]: _policy_target(raw) for key, raw in receipts}
            ended = dict(conn.execute(select(table.c.id, table.c.ended_at).where(table.c.store_id == self._context.scope.require_store_id(), table.c.id.in_([target for target in targets.values() if target is not None]))).all())
            pending = conn.execute(select(session_admissions.c.target_session_id, session_admissions.c.admission_id, session_admissions.c.seq, session_admissions.c.status).where(session_admissions.c.store_id == self._context.scope.require_store_id(), session_admissions.c.target_session_id.in_(session_ids), session_admissions.c.status.in_(('queued', 'started', 'unknown'))).order_by(session_admissions.c.seq)).mappings().all()
        by_session = {}
        for row in rows:
            row['title'] = decode_text(row['title'])
            row['target_ended_at'] = ended.get(targets.get(row['id']))
        for row in pending:
            by_session.setdefault(row['target_session_id'], []).append(dict(row))
        return ({row['id']: row for row in rows}, by_session)
