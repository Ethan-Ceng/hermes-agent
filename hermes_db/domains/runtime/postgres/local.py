"""Explicit runtime local component borrowing the owner context; no pools or session facade."""
import json
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.runtime.postgres.operations import local_sessions
from hermes_db.domains.runtime.postgres.queries import runtime, history_access
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_state_local import POLICY_PREFIX, _policy_target
from hermes_state_runtime import RuntimeStoreError, _json

class RuntimeLocal:

    def __init__(self, context):
        self._context = context

    def promote_current_history(self, *, epoch, actor, receipt, native_transport):
        from hermes_db.domains.runtime.postgres.operations.current_history import promote
        with self._context.write() as conn:
            return promote(conn, self._context.scope, epoch=epoch, actor=actor, receipt=receipt, own_profile=self._context.session.own_profile, native_transport=native_transport)

    def persist_hosted_binding(self, *, epoch, key, value):
        with self._context.write() as conn:
            runtime.require_epoch(conn, self._context.scope, epoch)
            sessions.lock_store(conn, self._context.scope, exclusive=True)
            old = runtime.meta(conn, self._context.scope, key)
            if old is not None and old != value:
                raise RuntimeStoreError('permission_denied')
            runtime.set_meta(conn, self._context.scope, key, value)

    def label_hosted_session(self, *, epoch, session_id, title):
        from hermes_db.core.values import encode_text
        with self._context.write() as conn:
            runtime.require_epoch(conn, self._context.scope, epoch)
            sessions.lock_store(conn, self._context.scope, exclusive=True)
            row = sessions.lock_session(conn, self._context.scope, session_id)
            if row is None or row['source'] != 'bot_room':
                raise RuntimeStoreError('permission_denied')
            sessions.update_session(conn, self._context.scope, session_id, {'title': encode_text(title), 'title_search': title, 'hidden': 1})

    def session_launch_source(self, session_id):
        from sqlalchemy import select
        from hermes_db.tables.conversations import sessions as table
        with self._context.read() as conn:
            return conn.scalar(select(table.c.source).where(table.c.store_id == self._context.scope.require_store_id(), table.c.id == session_id))

    def local_owner(self, session_id):
        from hermes_db.domains.runtime.postgres.queries.local_recovery import local_owner
        with self._context.read() as conn:
            return local_owner(conn, self._context.scope, session_id)

    def validate_local_lineage(self, receipt):
        from hermes_db.domains.sessions.postgres.queries.lineage import validate_local_receipt
        with self._context.read() as conn:
            return validate_local_receipt(conn, self._context.scope, receipt, receipt['session_id'])

    def local_receipt_ids(self):
        from hermes_db.domains.runtime.postgres.queries.local_recovery import receipt_ids
        with self._context.read() as conn:
            return receipt_ids(conn, self._context.scope)

    def unknown_inputs(self):
        from hermes_db.domains.runtime.postgres.queries.local_recovery import unknown_inputs
        with self._context.read() as conn:
            return unknown_inputs(conn, self._context.scope)

    def commit_local_session(self, *, epoch, receipt):
        publication = getattr(receipt, 'on_create', None)
        request = getattr(receipt, 'client_request', None)
        if request is None:
            if receipt['policy'].get('client_env_json') is not None:
                raise RuntimeStoreError('invalid_params')
            request = {}
        if publication is not None:
            publication.read()
        body = json.loads(_json(receipt))
        try:
            with self._context.write() as conn:
                return local_sessions.commit(conn, self._context.scope, epoch=epoch, receipt=body, request=request, own_profile=self._context.session.own_profile, publish=publication.publish if publication is not None else None)
        except UnknownCommitError:
            raise
        except BaseException:
            if publication is not None:
                publication.withdraw()
            raise

    def local_receipt(self, session_id):
        with self._context.read() as conn:
            raw = runtime.meta(conn, self._context.scope, POLICY_PREFIX + session_id)
        try:
            value = json.loads(raw) if raw is not None else None
        except (TypeError, ValueError):
            value = None
        if not isinstance(value, dict):
            raise RuntimeStoreError('storage_unavailable')
        return value

    def handoff_head(self, session_id):
        with self._context.read() as conn:
            row = sessions.raw_session(conn, self._context.scope, session_id)
            owner = row['chat_id'] if row and row['chat_id'] else session_id
            raw = runtime.meta(conn, self._context.scope, POLICY_PREFIX + owner)
            target = _policy_target(raw) if raw is not None else None
            start = target or session_id
            return (owner if target else None, sessions.compression_tip(conn, self._context.scope, start) or start)

    def end_idle_local_session(self, **kwargs):
        with self._context.write() as conn:
            return local_sessions.idle_end(conn, self._context.scope, **kwargs)

    def authorize_history(self, actor, session_id, *, native_transport):
        with self._context.read() as conn:
            return history_access.authorize_claim(conn, self._context.scope, actor, session_id, own_profile=self._context.session.own_profile, native_transport=native_transport)

    def require_history_leaf(self, session_id):
        from hermes_db.domains.sessions.postgres.operations.compression_state import lineage
        with self._context.read() as conn:
            history_access.require_leaf(conn, self._context.scope, session_id, lineage(conn, self._context.scope, session_id))
