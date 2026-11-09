"""SessionCatalog: explicit scoped session catalog operations sharing one resource context."""
import time
from sqlalchemy import select, func, text, delete, update, Text, cast, BigInteger, or_
from hermes_db.domains.sessions.postgres.operations import sessions as operations, titles
from hermes_db.domains.sessions.postgres.queries import sessions as repo, lineage_reads, session_queries as queries, sessions as prompt_refresh_sessions
from hermes_db.tables.conversations import sessions as metadata_sessions, messages, sessions as queries_sessions, sessions as titles_sessions, sessions as picker_reads_sessions, sessions as table
from hermes_db.core.values import encode_text, model_config, decode_text
import re
from hermes_db.domains.sessions.rules import sanitize_title
from sqlalchemy.dialects.postgresql import insert, JSONB
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings, telegram_dm_topic_mode as modes
import json
from hermes_db.domains.sessions.postgres.support.message_codec import content_from_bytes
from hermes_db.tables.runtime import state_meta
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_state_prompt_refresh import PROFILE_KEY, SESSION_KEY_PREFIX

def _profile(value):
    return str(value or '').strip() or 'default'

def _where(table, scope, **values):
    return (table.c.store_id == scope.require_store_id(), *(table.c[name] == value for name, value in values.items()))

def _row(value):
    return {key: field for key, field in value.items() if key != 'store_id'} if value else None

def _replies(conn, scope, segment):
    from agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY
    from hermes_db.backends.postgresql.expressions.projections import display_value, query_token
    from hermes_db.domains.sessions.postgres.support.message_codec import codec
    from hermes_db.domains.sessions.postgres.queries.messages import where, visible
    model_only = tuple(query_token(value) for value in (True, 1, 'true', '1'))
    rows = conn.execute(select(messages.c.content, messages.c._compressed_summary).where(where(scope, [segment]), messages.c.role == 'assistant', visible(), messages.c.content.is_not(None), messages.c.content != b'T', func.coalesce(messages.c.display_kind, '').not_in(['hidden', 'failed_turn']), func.coalesce(cast(display_value(messages.c.display_metadata, MODEL_ONLY_DISPLAY_METADATA_KEY), Text), 'false').not_in(model_only)).order_by(messages.c.id.desc()).limit(8))
    return [(codec._decode_content(content_from_bytes(content)), bool(summary)) for content, summary in rows]

class SessionCatalog:

    def __init__(self, context, flush_for_read, flush_token_counts):
        self._context = context
        self._flush_for_read = flush_for_read
        self._flush_token_counts = flush_token_counts

    def backfill_repo_roots(self, cwd_to_root):
        pairs = [(cwd, root) for cwd, root in cwd_to_root.items() if cwd and root]
        if not pairs:
            return
        with self._context.write() as conn:
            repo.lock_store(conn, self._context.scope, exclusive=True)
            for cwd, root in pairs:
                conn.execute(metadata_sessions.update().where(metadata_sessions.c.store_id == self._context.scope.require_store_id(), metadata_sessions.c.cwd == cwd, metadata_sessions.c.git_repo_root.is_(None) | (metadata_sessions.c.git_repo_root == '')).values(git_repo_root=root))

    def update_system_prompt(self, session_id, system_prompt):
        self._context.assert_open()
        operations.set_prompt(self._context.transactions, self._context.scope, session_id, system_prompt)

    def update_session_tool_names(self, session_id, pin):
        self._context.assert_open()
        operations.set_prompt(self._context.transactions, self._context.scope, session_id, pin, tools=True)

    def patch_session_model_config(self, session_id, patch):
        if session_id and patch:
            with self._context.write() as conn:
                operations.patch_model(conn, self._context.scope, session_id, patch)

    def get_session_model_config_value(self, session_id, key, default=None):
        return model_config((self.get_session(session_id) or {}).get('model_config')).get(key, default)

    def update_session_model(self, session_id, model, provider=None, *, base_url=None, api_mode=None):
        self._flush_token_counts()
        patch = {'browser_model_lock': None}
        if model:
            patch['model'] = model
        if provider:
            route = {'provider': provider, 'base_url': base_url or None, 'api_mode': api_mode or None}
            patch.update(route, gateway_runtime=route)
        with self._context.write() as conn:
            operations.patch_model(conn, self._context.scope, session_id, patch, extra={'model': model})

    def update_session_meta(self, session_id, model_config_json, model=None):
        self._flush_token_counts()
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            if row:
                repo.update_session(conn, self._context.scope, session_id, {'model_config': model_config_json, 'model': model or row['model']})

    def update_session_runtime_lock(self, session_id, *, model=None, provider=None, model_options=None, route_source=None, confirmed=False):
        lock = {'provider': provider or '', 'model': model or '', 'model_options': model_options or {}, 'route_source': route_source or '', 'confirmed': bool(confirmed), 'updated_at': time.time()}
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            if row:
                operations.patch_model(conn, self._context.scope, session_id, {'browser_model_lock': lock}, extra={'model': model if model is not None else row['model']})

    def update_conversation_model_config_value(self, session_id, key, update):
        with self._context.write() as conn:
            if repo.lock_session(conn, self._context.scope, session_id) is None:
                return None
            tip = repo.compression_tip(conn, self._context.scope, session_id)
            row = repo.raw_session(conn, self._context.scope, tip)
            config = model_config(row['model_config'])
            operations.patch_model(conn, self._context.scope, tip, {key: update(config.get(key))})
            return tip

    def session_ids_with_model_config_key(self, key):
        from hermes_db.backends.postgresql.expressions.json_paths import path_value
        found, cursor = ([], None)
        with self._context.read() as conn:
            statement = select(metadata_sessions.c.id, metadata_sessions.c.started_at, metadata_sessions.c.model_config).where(metadata_sessions.c.store_id == self._context.scope.require_store_id()).order_by(metadata_sessions.c.id).limit(128)
            while True:
                page = statement.where(metadata_sessions.c.id > cursor) if cursor is not None else statement
                rows = conn.execute(page).mappings().all()
                if not rows:
                    break
                found.extend((row['started_at'], row['id']) for row in rows if path_value(model_config(row['model_config']), key) is not None)
                cursor = rows[-1]['id']
        return [session_id for _, session_id in sorted(found, key=lambda item: item[0], reverse=True)]

    def set_session_yolo(self, session_id, enabled):
        self.patch_session_model_config(session_id, {'yolo_mode': bool(enabled)})

    @staticmethod
    def session_yolo_enabled(session_meta):
        return bool(model_config((session_meta or {}).get('model_config')).get('yolo_mode'))

    def set_expiry_finalized(self, session_id, finalized=True):
        with self._context.write() as conn:
            repo.lock_session(conn, self._context.scope, session_id)
            repo.update_session(conn, self._context.scope, session_id, {'expiry_finalized': int(finalized)})

    def set_session_archived(self, session_id, archived, *, notify=True):
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            ids = operations.lineage_flag(conn, self._context.scope, session_id, 'archived', int(archived), extra={'auto_archived': 0})
            if archived:
                from hermes_db.domains.sessions.postgres.operations.titles import retire_bot_chat
                retire_bot_chat(conn, self._context.scope, ids)
            newly_archived = archived and row and (not row['archived'])
        if newly_archived and notify:
            from hermes_db.integration.events import emit_deleted
            emit_deleted(self._context.profile, ids, reason='archive', primary=session_id)
        return bool(ids)

    def set_session_hidden(self, session_id, hidden):
        with self._context.write() as conn:
            return bool(operations.lineage_flag(conn, self._context.scope, session_id, 'hidden', int(hidden)))

    def set_session_pinned(self, session_id, pinned):
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            ids = operations.lineage_flag(conn, self._context.scope, session_id, 'pinned', int(pinned))
            canonical = row and row['hidden'] and (row['title'] == encode_text(self.CANONICAL_BOT_CHAT_TITLE))
            if pinned and (not canonical):
                operations.lineage_flag(conn, self._context.scope, session_id, 'hidden', 0)
            return bool(ids)

    def set_session_read(self, session_id, read=True):
        with self._context.write() as conn:
            return bool(operations.lineage_flag(conn, self._context.scope, session_id, 'last_read_at', time.time() if read else 0.0))

    @staticmethod
    def session_unread(session_row):
        if session_row.get('last_read_at') is None:
            return False
        active = session_row.get('last_active') or session_row.get('started_at')
        return float(active or 0) > float(session_row['last_read_at'])

    def update_session_cwd(self, session_id, cwd, git_branch=None, git_repo_root=None, replace_git_meta=False):
        if not session_id or not cwd:
            return None
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            if row is None:
                return None
            generation = int(row['git_metadata_generation'] or 0) + 1
            values = {'cwd': cwd, 'git_metadata_generation': generation}
            for name, value in (('git_branch', git_branch), ('git_repo_root', git_repo_root)):
                value = (value or '').strip()
                if value or replace_git_meta or row['cwd'] != cwd:
                    values[name] = value or None
            repo.update_session(conn, self._context.scope, session_id, values)
            return generation

    def publish_session_git_metadata(self, session_id, cwd, generation, git_branch=None, git_repo_root=None):
        if not session_id or not cwd or type(generation) is not int or (generation < 1):
            return False
        values = {name: value.strip() for name, value in (('git_branch', git_branch), ('git_repo_root', git_repo_root)) if value and value.strip()}
        if not values:
            return False
        with self._context.write() as conn:
            repo.lock_session(conn, self._context.scope, session_id)
            return repo.update_session(conn, self._context.scope, session_id, values, metadata_sessions.c.cwd == cwd, metadata_sessions.c.git_metadata_generation == generation) == 1

    def touch_session_activity(self, session_id, ts=None, *, description=None, provenance=None):
        from agent.session_activity import bound_activity_description, normalize_activity_provenance
        if not session_id:
            return
        when = float(time.time() if ts is None else ts)
        with self._context.write() as conn:
            repo.lock_session(conn, self._context.scope, session_id)
            repo.update_session(conn, self._context.scope, session_id, {'last_activity_at': when, 'last_activity_description': encode_text(bound_activity_description(description)), 'last_activity_provenance': normalize_activity_provenance(provenance).value}, metadata_sessions.c.last_activity_at.is_(None) | (metadata_sessions.c.last_activity_at < when))

    def clear_session_activity_labels(self, session_id):
        if not session_id:
            return
        with self._context.write() as conn:
            repo.lock_session(conn, self._context.scope, session_id)
            repo.update_session(conn, self._context.scope, session_id, {'last_activity_description': b'', 'last_activity_provenance': 'unknown'})

    def retire_undrained_queue_rows(self, session_id):
        with self._context.write() as conn:
            if repo.lock_session(conn, self._context.scope, session_id) is None:
                return 0
            return operations.retire_queued_on_connection(conn, self._context.scope, session_id)

    def promote_to_session_reset(self, session_id, reason='session_reset'):
        from hermes_state_common import _RECOVERABLE_END_REASONS
        if not session_id:
            return False
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            if row is None or (row['ended_at'] is not None and row['end_reason'] not in _RECOVERABLE_END_REASONS):
                return False
            repo.update_session(conn, self._context.scope, session_id, {'ended_at': time.time(), 'end_reason': reason})
            repo.bump_generation(conn, self._context.scope, row, reason)
            return True

    def unarchive_recoverable_session(self, session_id):
        from hermes_state_common import _RECOVERABLE_END_REASONS
        if not session_id:
            return False
        with self._context.write() as conn:
            row = repo.lock_session(conn, self._context.scope, session_id)
            if row is None or not row['archived']:
                return False
            tip_id = repo.compression_tip(conn, self._context.scope, session_id)
            tip = repo.raw_session(conn, self._context.scope, tip_id)
            if tip['end_reason'] not in _RECOVERABLE_END_REASONS:
                return False
            operations.lineage_flag(conn, self._context.scope, session_id, 'archived', 0, extra={'auto_archived': 0})
            repo.update_session(conn, self._context.scope, tip_id, {'ended_at': None, 'end_reason': None})
            return True

    def declared_scope_identity(self, session_id):
        self._flush_for_read()
        with self._context.read() as conn:
            return lineage_reads.declared_scope_identity(conn, self._context.scope, session_id)

    def create_session(self, session_id, source, **kwargs):
        self._context.assert_open()
        return operations.create(self._context.transactions, self._context.scope, session_id, source, own_profile=self._context.own_profile, **kwargs)

    def ensure_session(self, session_id, source='unknown', model=None, **kwargs):
        return self.create_session(session_id, source, model=model, **kwargs)

    def get_session(self, session_id):
        self._flush_for_read()
        with self._context.read() as conn:
            return repo.get_session(conn, self._context.scope, session_id)

    def end_session(self, session_id, end_reason):
        self._context.assert_open()
        operations.end(self._context.transactions, self._context.scope, session_id, end_reason)

    def reopen_session(self, session_id):
        self._context.assert_open()
        operations.reopen(self._context.transactions, self._context.scope, session_id)

    def get_session_rich_row(self, session_id, compact_rows=False):
        self._flush_for_read()
        with self._context.read() as conn:
            rows = queries.hydrate(conn, self._context.scope, [session_id], compact=compact_rows)
            return rows[0] if rows else None

    def get_session_list_row(self, session_id):
        fields = ('id', 'source', 'title', 'started_at', 'ended_at', 'message_count', 'model', 'hidden', 'archived')
        with self._context.read() as conn:
            row = conn.execute(select(*(queries_sessions.c[name] for name in fields)).where(repo.where_session(self._context.scope, session_id))).mappings().one_or_none()
            return repo.business_row(row) if row else None

    def resolve_session_id(self, session_id_or_prefix):
        with self._context.read() as conn:
            exact = conn.scalar(select(queries_sessions.c.id).where(repo.where_session(self._context.scope, session_id_or_prefix)))
            if exact:
                return exact
            rows = list(conn.execute(select(queries_sessions.c.id).where(queries_sessions.c.store_id == self._context.scope.require_store_id(), queries_sessions.c.id.startswith(session_id_or_prefix, autoescape=True)).limit(2)).scalars())
            return rows[0] if len(rows) == 1 else None

    def find_session_by_origin(self, *, platform, chat_id, thread_id=None, user_id=None):
        if not platform or chat_id in (None, ''):
            return None
        with self._context.read() as conn:
            statement = select(queries_sessions.c.id, queries_sessions.c.user_id).where(queries_sessions.c.store_id == self._context.scope.require_store_id(), func.lower(queries_sessions.c.source) == platform.lower(), queries_sessions.c.session_key.is_not(None), queries_sessions.c.chat_id == str(chat_id), queries_sessions.c.ended_at.is_(None))
            if thread_id is not None:
                statement = statement.where(func.coalesce(queries_sessions.c.thread_id, '') == str(thread_id))
            rows = list(conn.execute(statement.order_by(queries_sessions.c.started_at.desc())).mappings())
        if not rows:
            return None
        if user_id:
            exact = [row for row in rows if str(row['user_id'] or '') == str(user_id)]
            if exact:
                return exact[0]['id']
            if len(rows) > 1:
                return None
        elif len({str(row['user_id'] or '').strip() for row in rows if row['user_id']}) > 1:
            return None
        return rows[0]['id']

    def list_sessions_rich(self, source=None, sources=None, exclude_sources=None, cwd_prefix=None, limit=20, offset=0, include_children=False, min_message_count=0, project_compression_tips=True, order_by_last_active=False, include_archived=False, archived_only=False, id_query=None, search_query=None, compact_rows=False, include_pinned=False, session_key=None, include_hidden=False, include_subagents=False, local_created_sources=None, workspace_key=None):
        arguments = dict(source=source, sources=sources, session_key=session_key, exclude_sources=exclude_sources, cwd_prefix=cwd_prefix, workspace_key=workspace_key, min_message_count=min_message_count, include_archived=include_archived, archived_only=archived_only, exclude_children=not include_children, include_subagents=include_subagents, local_created_sources=local_created_sources, include_hidden=include_hidden)
        with self._context.read() as conn:
            clauses = queries.filters(conn, self._context.scope, **arguments)
            if order_by_last_active:
                clauses += queries.search_filters(conn, id_query, search_query)
            order = queries.lineage_activity(conn).desc() if order_by_last_active else queries_sessions.c.started_at.desc()
            statement = select(queries_sessions.c.id).where(*clauses).order_by(order, queries_sessions.c.started_at.desc(), queries_sessions.c.id.desc())
            ids = list(conn.execute(statement.limit(None if limit < 0 else limit).offset(offset)).scalars())
            if include_pinned:
                arguments.update(include_archived=True, archived_only=False)
                pinned = select(queries_sessions.c.id).where(*queries.filters(conn, self._context.scope, **arguments), queries_sessions.c.pinned == 1)
                ids.extend(session_id for session_id in conn.execute(pinned.order_by(queries_sessions.c.started_at.desc())).scalars() if session_id not in ids)
            rows = queries.hydrate(conn, self._context.scope, ids, compact=compact_rows)
            if project_compression_tips and (not include_children):
                rows = queries.project_tips(conn, self._context.scope, rows, compact=compact_rows)
            return rows

    def session_count(self, source=None, sources=None, cwd_prefix=None, min_message_count=0, include_archived=False, archived_only=False, exclude_children=False, exclude_sources=None, include_subagents=False, local_created_sources=None):
        arguments = {key: value for key, value in locals().items() if key != 'self'}
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(queries_sessions).where(*queries.filters(conn, self._context.scope, **arguments)))

    def session_count_ge(self, n=1):
        if n <= 0:
            return True
        with self._context.read() as conn:
            return len(list(conn.execute(select(queries_sessions.c.id).where(queries_sessions.c.store_id == self._context.scope.require_store_id()).limit(n)).scalars())) >= n

    def session_count_by_source(self, *, include_archived=False, archived_only=False, exclude_children=False):
        with self._context.read() as conn:
            name = func.coalesce(func.nullif(queries_sessions.c.source, ''), 'cli')
            rows = conn.execute(select(name, func.count()).where(*queries.filters(conn, self._context.scope, include_archived=include_archived, archived_only=archived_only, exclude_children=exclude_children)).group_by(name).order_by(func.count().desc()))
            return {source: count for source, count in rows}

    def search_sessions(self, source=None, limit=20, offset=0, workspace_key=None, local_created_sources=None, skip_launch_stubs=False):
        with self._context.read() as conn:
            labels = [source] if isinstance(source, str) else source
            clauses = queries.filters(conn, self._context.scope, sources=labels, include_archived=True, local_created_sources=local_created_sources)
            if workspace_key:
                clauses.append((queries_sessions.c.git_repo_root == workspace_key) | (func.coalesce(queries_sessions.c.git_repo_root, '') == '') & ((queries_sessions.c.cwd == workspace_key) | queries_sessions.c.cwd.startswith(workspace_key.rstrip('/\\') + '/', autoescape=True) | queries_sessions.c.cwd.startswith(workspace_key.rstrip('/\\') + '\\', autoescape=True)))
            if skip_launch_stubs:
                clauses.append(queries.launch_stub_filter(self._context.scope))
            ids = list(conn.execute(select(queries_sessions.c.id).where(*clauses).order_by(queries.last_activity(conn).desc(), queries_sessions.c.started_at.desc(), queries_sessions.c.id.desc()).limit(None if limit < 0 else limit).offset(offset)).scalars())
            return queries.hydrate(conn, self._context.scope, ids)

    def list_recent_sessions_bounded(self, *, limit=20, exclude_sources=None, timeout_seconds=3.0, candidate_limit=None, lineage_limit=None):
        limit = max(1, int(limit))
        candidates = max(limit, min(int(candidate_limit or max(128, limit * 8)), 2048))
        ceiling = max(candidates, min(int(lineage_limit or min(8192, candidates * 8)), 8192))
        with self._context.read() as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {'timeout': str(max(1, int(timeout_seconds * 1000)))})
            roots = queries.bounded_roots(conn, self._context.scope, exclude_sources, candidates, ceiling)
            clauses = queries.filters(conn, self._context.scope, exclude_sources=exclude_sources, exclude_children=True, include_hidden=False)
            clauses.append(queries_sessions.c.id.in_(roots))
            ids = list(conn.execute(select(queries_sessions.c.id).where(*clauses).order_by(queries.lineage_activity(conn).desc(), queries_sessions.c.id.desc()).limit(limit)).scalars())
            rows = queries.project_tips(conn, self._context.scope, queries.hydrate(conn, self._context.scope, ids))
            for row in rows:
                row['unread'] = self.session_unread(row)
            return rows

    def session_lifecycle_statuses(self, session_ids):
        from hermes_state_sessions import classify_session_status
        ids = [value for value in session_ids or [] if value]
        result = {value: 'empty' for value in ids}
        if not ids:
            return result
        with self._context.read() as conn:
            latest = select(messages.c.session_id, func.max(messages.c.id).label('latest_id')).where(messages.c.store_id == self._context.scope.require_store_id(), messages.c.session_id.in_(ids)).group_by(messages.c.session_id).subquery()
            rows = conn.execute(select(messages.c.session_id, messages.c.role, messages.c.tool_calls, messages.c.finish_reason).join(latest, (messages.c.session_id == latest.c.session_id) & (messages.c.id == latest.c.latest_id)).where(messages.c.store_id == self._context.scope.require_store_id())).mappings()
            for row in rows:
                result[row['session_id']] = classify_session_status(row['role'], row['tool_calls'] is not None, row['finish_reason'])
        return result

    def count_empty_sessions(self):
        from sqlalchemy import exists
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(queries_sessions).where(queries_sessions.c.store_id == self._context.scope.require_store_id(), queries_sessions.c.message_count == 0, queries_sessions.c.ended_at.is_not(None), queries_sessions.c.archived == 0, ~exists(select(1).where(messages.c.store_id == queries_sessions.c.store_id, messages.c.session_id == queries_sessions.c.id))))
    MAX_TITLE_LENGTH = 100
    TITLE_SOURCE_DERIVED, TITLE_SOURCE_LLM, TITLE_SOURCE_USER = ('derived', 'llm', 'user')
    CANONICAL_BOT_CHAT_TITLE = titles.BOT_TITLE

    @staticmethod
    def sanitize_title(value):
        return sanitize_title(value)

    def set_session_title(self, session_id, title):
        self._context.assert_open()
        return titles.set_title(self._context.transactions, self._context.scope, session_id, title, 'user')

    def set_auto_title(self, session_id, title, *, source):
        self._context.assert_open()
        if source not in ('derived', 'llm'):
            raise ValueError('Invalid automatic title source')
        return titles.set_title(self._context.transactions, self._context.scope, session_id, title, source)

    def displace_bot_chat(self, session_id, title):
        with self._context.write() as conn:
            repo.lock_store(conn, self._context.scope, exclusive=True)
            repo.lock_session(conn, self._context.scope, session_id)
            return repo.update_session(conn, self._context.scope, session_id, {'title': encode_text(title), 'title_search': title, 'title_source': 'user', 'hidden': 0}, titles_sessions.c.title == encode_text('Bot Chat')) > 0

    def get_session_title(self, session_id):
        row = self.get_session(session_id)
        return row['title'] if row else None

    def get_session_title_source(self, session_id):
        row = self.get_session(session_id)
        return row['title_source'] if row and row['title'] is not None else None

    def set_session_title_source(self, session_id, source):
        if source not in titles.RANK:
            raise ValueError('Invalid title source')
        with self._context.write() as conn:
            repo.lock_session(conn, self._context.scope, session_id)
            return repo.update_session(conn, self._context.scope, session_id, {'title_source': source}, titles_sessions.c.title.is_not(None)) > 0

    def get_session_by_title(self, title):
        with self._context.read() as conn:
            session_id = conn.scalar(select(titles_sessions.c.id).where(titles_sessions.c.store_id == self._context.scope.require_store_id(), titles_sessions.c.title == encode_text(title)))
            row = repo.get_session(conn, self._context.scope, session_id) if session_id else None
            if row and title == titles.BOT_TITLE and row['archived']:
                from hermes_state_titles import bot_chat_title_released
                tip = repo.raw_session(conn, self._context.scope, repo.compression_tip(conn, self._context.scope, row['id'])) or row
                if bot_chat_title_released(row['archived'], row['auto_archived'], tip['end_reason']):
                    return None
            return row

    def resolve_session_by_title(self, title):
        exact = self.get_session_by_title(title)
        if title == titles.BOT_TITLE:
            return exact['id'] if exact else None
        with self._context.read() as conn:
            latest = conn.scalar(select(titles_sessions.c.id).where(titles_sessions.c.store_id == self._context.scope.require_store_id(), titles_sessions.c.title_search.startswith(title + ' #', autoescape=True)).order_by(titles_sessions.c.started_at.desc(), titles_sessions.c.id.desc()).limit(1))
        return latest or (exact['id'] if exact else None)

    def get_next_title_in_lineage(self, base_title):
        base = re.sub(' #\\d+$', '', base_title)
        with self._context.read() as conn:
            rows = conn.execute(select(titles_sessions.c.title).where(titles_sessions.c.store_id == self._context.scope.require_store_id(), (titles_sessions.c.title == encode_text(base)) | titles_sessions.c.title_search.startswith(base + ' #', autoescape=True))).scalars()
            values = [decode_text(value) for value in rows]
        if not values:
            return base
        numbers = [int(value.rsplit(' #', 1)[1]) for value in values if re.fullmatch(re.escape(base) + ' #\\d+', value)]
        return f'{base} #{max([1, *numbers]) + 1}'

    def apply_telegram_topic_migration(self):
        """Alembic installs the PG tables up front; this does not activate topic mode."""
        self._context.assert_open()

    def enable_telegram_topic_mode(self, *, chat_id, user_id, profile_name='default', has_topics_enabled=None, allows_users_to_create_topics=None):
        now = time.time()
        values = dict(store_id=self._context.scope.require_store_id(), profile_name=_profile(profile_name), chat_id=str(chat_id), user_id=str(user_id), enabled=1, activated_at=now, updated_at=now, capability_checked_at=now, has_topics_enabled=None if has_topics_enabled is None else int(bool(has_topics_enabled)), allows_users_to_create_topics=None if allows_users_to_create_topics is None else int(bool(allows_users_to_create_topics)))
        with self._context.write() as conn:
            repo.lock_store(conn, self._context.scope, exclusive=True)
            statement = insert(modes).values(**values)
            updates = {key: value for key, value in values.items() if key not in ('store_id', 'profile_name', 'chat_id', 'activated_at')}
            conn.execute(statement.on_conflict_do_update(index_elements=list(modes.primary_key.columns), set_=updates))

    def disable_telegram_topic_mode(self, *, chat_id, profile_name='default', clear_bindings=True):
        values = {'profile_name': _profile(profile_name), 'chat_id': str(chat_id)}
        with self._context.write() as conn:
            repo.lock_store(conn, self._context.scope, exclusive=True)
            conn.execute(update(modes).where(*_where(modes, self._context.scope, **values)).values(enabled=0, updated_at=time.time()))
            if clear_bindings:
                conn.execute(delete(bindings).where(*_where(bindings, self._context.scope, **values)))

    def is_telegram_topic_mode_enabled(self, *, chat_id, user_id, profile_name='default'):
        with self._context.read() as conn:
            return bool(conn.scalar(select(modes.c.enabled).where(*_where(modes, self._context.scope, profile_name=_profile(profile_name), chat_id=str(chat_id), user_id=str(user_id)))))

    def get_telegram_topic_binding(self, *, chat_id, thread_id, profile_name='default'):
        with self._context.read() as conn:
            return _row(conn.execute(select(bindings).where(*_where(bindings, self._context.scope, profile_name=_profile(profile_name), chat_id=str(chat_id), thread_id=str(thread_id)))).mappings().one_or_none())

    def list_telegram_topic_bindings_for_chat(self, *, chat_id, profile_name='default'):
        with self._context.read() as conn:
            return [_row(row) for row in conn.execute(select(bindings).where(*_where(bindings, self._context.scope, profile_name=_profile(profile_name), chat_id=str(chat_id))).order_by(bindings.c.updated_at.desc())).mappings()]

    def get_telegram_topic_binding_by_session(self, *, session_id):
        with self._context.read() as conn:
            return _row(conn.execute(select(bindings).where(*_where(bindings, self._context.scope, session_id=str(session_id)))).mappings().one_or_none())

    def is_telegram_session_linked_to_topic(self, *, session_id):
        return self.get_telegram_topic_binding_by_session(session_id=session_id) is not None

    def bind_telegram_topic(self, *, chat_id, thread_id, user_id, session_key, session_id, managed_mode='auto', profile_name='default', expected_session_id=None):
        profile_name, chat_id, thread_id = (_profile(profile_name), str(chat_id), str(thread_id))
        now = time.time()
        with self._context.write() as conn:
            repo.lock_store(conn, self._context.scope, exclusive=True)
            if expected_session_id is not None:
                current = conn.scalar(select(bindings.c.session_id).where(*_where(bindings, self._context.scope, profile_name=profile_name, chat_id=chat_id, thread_id=thread_id)))
                if current is None or current != str(expected_session_id):
                    return False
            existing = conn.execute(select(bindings).where(*_where(bindings, self._context.scope, session_id=str(session_id)))).mappings().one_or_none()
            if existing and (existing['profile_name'], existing['chat_id'], existing['thread_id']) != (profile_name, chat_id, thread_id):
                raise ValueError('session is already linked to another Telegram topic')
            values = dict(store_id=self._context.scope.require_store_id(), profile_name=profile_name, chat_id=chat_id, thread_id=thread_id, user_id=str(user_id), session_key=str(session_key), session_id=str(session_id), managed_mode=managed_mode, linked_at=now, updated_at=now)
            statement = insert(bindings).values(**values)
            changed = {key: value for key, value in values.items() if key not in ('store_id', 'profile_name', 'chat_id', 'thread_id', 'linked_at')}
            conn.execute(statement.on_conflict_do_update(index_elements=list(bindings.primary_key.columns), set_=changed))
            return True

    def delete_telegram_topic_binding(self, *, chat_id, thread_id, profile_name='default'):
        values = {'profile_name': _profile(profile_name), 'chat_id': str(chat_id)}
        with self._context.write() as conn:
            repo.lock_store(conn, self._context.scope, exclusive=True)
            deleted = conn.execute(delete(bindings).where(*_where(bindings, self._context.scope, **values, thread_id=str(thread_id)))).rowcount
            if deleted and (not conn.scalar(select(func.count()).select_from(bindings).where(*_where(bindings, self._context.scope, **values)))):
                conn.execute(update(modes).where(*_where(modes, self._context.scope, **values)).values(enabled=0, updated_at=time.time()))
            return deleted

    def list_unlinked_telegram_sessions_for_user(self, *, chat_id, user_id, profile_name='default', limit=10):
        from sqlalchemy import exists
        from hermes_db.domains.sessions.postgres.queries import session_queries as queries
        from hermes_db.tables.conversations import sessions
        with self._context.read() as conn:
            statement = select(sessions.c.id).where(sessions.c.store_id == self._context.scope.require_store_id(), sessions.c.source == 'telegram', sessions.c.user_id == str(user_id), func.coalesce(func.nullif(func.trim(sessions.c.profile_name), ''), 'default') == _profile(profile_name), ~exists(select(1).where(bindings.c.store_id == sessions.c.store_id, bindings.c.session_id == sessions.c.id)))
            ids = list(conn.execute(statement.order_by(queries.last_activity(conn).desc(), sessions.c.started_at.desc()).limit(None if limit < 0 else limit)).scalars())
            return queries.hydrate(conn, self._context.scope, ids)

    def sessions_in_workspace(self, session_ids, workspace):
        with self._context.read() as conn:
            return set(conn.execute(select(picker_reads_sessions.c.id).where(picker_reads_sessions.c.store_id == self._context.scope.require_store_id(), picker_reads_sessions.c.id.in_(list(session_ids)), queries.workspace_clause(workspace))).scalars())

    def picker_session_facts(self, root_ids, unlisted_ids, segment_ids):
        with self._context.read() as conn:
            owner = picker_reads_sessions.c.store_id == self._context.scope.require_store_id()
            roots = {row['id']: dict(row) for row in conn.execute(select(picker_reads_sessions.c.id, picker_reads_sessions.c.cwd, picker_reads_sessions.c.git_repo_root).where(owner, picker_reads_sessions.c.id.in_(list(root_ids)))).mappings()}
            ids = list(unlisted_ids)
            unlisted = {row['id']: dict(row) for row in conn.execute(select(picker_reads_sessions.c.id, picker_reads_sessions.c.git_branch, picker_reads_sessions.c.pinned, queries.last_activity(conn).label('last_active')).where(owner, picker_reads_sessions.c.id.in_(ids))).mappings()}
            ranked = select(messages.c.session_id, messages.c.preview_text, func.row_number().over(partition_by=messages.c.session_id, order_by=(messages.c.timestamp, messages.c.id)).label('n')).where(messages.c.store_id == self._context.scope.require_store_id(), messages.c.session_id.in_(ids), messages.c.role == 'user', messages.c.preview_text.is_not(None)).subquery()
            previews = dict(conn.execute(select(ranked.c.session_id, ranked.c.preview_text).where(ranked.c.n == 1)).all())
            for sid, row in unlisted.items():
                row['_preview_raw'] = decode_text(previews.get(sid))
            replies = {segment: _replies(conn, self._context.scope, segment) for segment in set(segment_ids)}
            return (roots, unlisted, replies)

    def session_current_segments(self, session_ids):
        from hermes_state_local import POLICY_PREFIX
        with self._context.read() as conn:
            rows = conn.execute(select(picker_reads_sessions.c.id, picker_reads_sessions.c.end_reason, state_meta.c.value).outerjoin(state_meta, (state_meta.c.store_id == picker_reads_sessions.c.store_id) & (state_meta.c.key == POLICY_PREFIX + picker_reads_sessions.c.id)).where(picker_reads_sessions.c.store_id == self._context.scope.require_store_id(), picker_reads_sessions.c.id.in_(list(session_ids)))).mappings()
            result = {}
            for row in rows:
                receipt = json.loads(row['value']) if row['value'] else {}
                entry = (receipt.get('entry') or {}).get('session_id')
                result[row['id']] = entry or (repo.compression_tip(conn, self._context.scope, row['id']) if row['end_reason'] == 'compression' else row['id'])
            return result

    def subagent_session_ids(self, subagent_id, marker_key):
        with self._context.read() as conn:
            return list(conn.execute(select(picker_reads_sessions.c.id).where(picker_reads_sessions.c.store_id == self._context.scope.require_store_id(), picker_reads_sessions.c.source == 'subagent', cast(picker_reads_sessions.c.model_config, JSONB)[marker_key].astext == subagent_id).order_by(picker_reads_sessions.c.started_at.desc(), picker_reads_sessions.c.id.desc())).scalars())

    def request_prompt_refresh(self, session_id=None):
        key = PROFILE_KEY if session_id is None else SESSION_KEY_PREFIX + session_id
        with self._context.write() as conn:
            prompt_refresh_sessions.lock_store(conn, self._context.scope, exclusive=True)
            epoch = 1 + (conn.scalar(select(func.max(cast(state_meta.c.value, BigInteger))).where(state_meta.c.store_id == self._context.scope.require_store_id(), or_(state_meta.c.key == PROFILE_KEY, state_meta.c.key.startswith(SESSION_KEY_PREFIX, autoescape=True)))) or 0)
            runtime.set_meta(conn, self._context.scope, key, str(epoch))
        return epoch

    def prompt_refresh_epoch(self, session_id):
        with self._context.read() as conn:
            return conn.scalar(select(func.max(cast(state_meta.c.value, BigInteger))).where(state_meta.c.store_id == self._context.scope.require_store_id(), state_meta.c.key.in_((PROFILE_KEY, SESSION_KEY_PREFIX + session_id)))) or 0

    def count_sessions_with_stored_prompt(self):
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(table).where(table.c.store_id == self._context.scope.require_store_id(), or_(table.c.system_prompt_hash.is_not(None), table.c.system_prompt.is_not(None))))
