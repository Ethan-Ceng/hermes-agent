"""Scoped store facts shared by session pickers and delegated transcript readers."""

import json
from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

from hermes_db.message_codec import content_from_bytes
from hermes_db.repositories import sessions as repo, session_queries as queries
from hermes_db.tables.conversations import messages, sessions
from hermes_db.tables.runtime import state_meta
from hermes_db.core.values import decode_text


class SessionPickerReads:
    def sessions_in_workspace(self, session_ids, workspace):
        with self._read() as conn:
            return set(conn.execute(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.id.in_(list(session_ids)), queries.workspace_clause(workspace))).scalars())

    def picker_session_facts(self, root_ids, unlisted_ids, segment_ids):
        with self._read() as conn:
            owner = sessions.c.store_id == self.scope.require_store_id()
            roots = {row['id']: dict(row) for row in conn.execute(select(sessions.c.id, sessions.c.cwd,
                sessions.c.git_repo_root).where(owner, sessions.c.id.in_(list(root_ids)))).mappings()}
            ids = list(unlisted_ids)
            unlisted = {row['id']: dict(row) for row in conn.execute(select(sessions.c.id, sessions.c.git_branch,
                sessions.c.pinned, queries.last_activity(conn).label('last_active')).where(owner, sessions.c.id.in_(ids))).mappings()}
            ranked = select(messages.c.session_id, messages.c.preview_text, func.row_number().over(
                partition_by=messages.c.session_id, order_by=(messages.c.timestamp, messages.c.id)).label('n')).where(
                    messages.c.store_id == self.scope.require_store_id(), messages.c.session_id.in_(ids),
                    messages.c.role == 'user', messages.c.preview_text.is_not(None)).subquery()
            previews = dict(conn.execute(select(ranked.c.session_id, ranked.c.preview_text).where(ranked.c.n == 1)).all())
            for sid, row in unlisted.items():
                row['_preview_raw'] = decode_text(previews.get(sid))
            replies = {segment: _replies(conn, self.scope, segment) for segment in set(segment_ids)}
            return roots, unlisted, replies

    def session_current_segments(self, session_ids):
        from hermes_state_local import POLICY_PREFIX
        with self._read() as conn:
            rows = conn.execute(select(sessions.c.id, sessions.c.end_reason, state_meta.c.value).outerjoin(state_meta,
                (state_meta.c.store_id == sessions.c.store_id) & (state_meta.c.key == POLICY_PREFIX + sessions.c.id)).where(
                    sessions.c.store_id == self.scope.require_store_id(), sessions.c.id.in_(list(session_ids)))).mappings()
            result = {}
            for row in rows:
                receipt = json.loads(row['value']) if row['value'] else {}
                entry = (receipt.get('entry') or {}).get('session_id')
                result[row['id']] = entry or (repo.compression_tip(conn, self.scope, row['id'])
                                              if row['end_reason'] == 'compression' else row['id'])
            return result

    def subagent_session_ids(self, subagent_id, marker_key):
        with self._read() as conn:
            return list(conn.execute(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.source == 'subagent', cast(sessions.c.model_config, JSONB)[marker_key].astext == subagent_id)
                .order_by(sessions.c.started_at.desc(), sessions.c.id.desc())).scalars())


def _replies(conn, scope, segment):
    from agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY
    from hermes_db.backends.postgresql.expressions.projections import display_value, query_token
    from hermes_db.message_codec import codec
    from hermes_db.repositories.messages import where, visible
    model_only = tuple(query_token(value) for value in (True, 1, 'true', '1'))
    rows = conn.execute(select(messages.c.content, messages.c._compressed_summary).where(where(scope, [segment]),
        messages.c.role == 'assistant', visible(), messages.c.content.is_not(None), messages.c.content != b'T',
        func.coalesce(messages.c.display_kind, '').not_in(['hidden', 'failed_turn']),
        func.coalesce(cast(display_value(messages.c.display_metadata, MODEL_ONLY_DISPLAY_METADATA_KEY), Text), 'false').not_in(model_only))
        .order_by(messages.c.id.desc()).limit(8))
    return [(codec._decode_content(content_from_bytes(content)), bool(summary)) for content, summary in rows]
