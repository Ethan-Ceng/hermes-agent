"""SessionMessages: explicit scoped session messages operations sharing one resource context."""
from hermes_db.domains.sessions.postgres.operations import messages as operations, transcript_guards
from sqlalchemy import Text, cast, func, select
from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo, lineage_reads
from hermes_db.tables.conversations import messages, sessions
from hermes_db.domains.sql.postgresql import display_value, query_token
import time
import json
from hermes_state_identity import _uid_list

def _active_filter(include_inactive, include_compacted):
    return [] if include_inactive else [repo.visible() if include_compacted else messages.c.active == 1]

def _page(rows, limit, offset, latest):
    return rows[::-1][offset:][:limit][::-1] if latest else rows[offset:][:limit]

def _resume_count(conn, scope, session_id, tip_only, limit=None):
    ids = [session_id] if tip_only else repo.resume_lineage(conn, scope, session_id)
    statement = select(messages.c.id).where(repo.where(scope, ids), messages.c.active == 1 if tip_only else repo.visible())
    if limit is not None:
        statement = statement.limit(limit)
    return conn.scalar(select(func.count()).select_from(statement.subquery()))

def display_ids(conn, scope, session_id, limit=None, offset=0, latest=False, after=None):
    from hermes_db.domains.sql.postgresql import display_value, query_token
    from agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY
    original = messages.alias('original')
    model_only = tuple(query_token(value) for value in (True, 1, 'true', '1'))
    copied_tool = select(1).where(original.c.store_id == messages.c.store_id, original.c.session_id == messages.c.session_id, original.c.timestamp == messages.c.timestamp, original.c.message_uid == messages.c.message_uid, original.c.role == 'tool', original.c.active == 0, original.c.compacted == 1, original.c.display_order < messages.c.display_order, func.coalesce(cast(display_value(original.c.display_metadata, MODEL_ONLY_DISPLAY_METADATA_KEY), Text), 'false').not_in(model_only)).exists()
    eligible = [repo.where(scope, [session_id]), repo.visible(), func.coalesce(cast(display_value(messages.c.display_metadata, MODEL_ONLY_DISPLAY_METADATA_KEY), Text), 'false').not_in(model_only), ~((messages.c.role == 'tool') & messages.c.message_uid.is_not(None) & copied_tool)]
    if after is not None:
        eligible.append(messages.c.display_order < after if latest else messages.c.display_order > after)
    ranked = select(messages.c.id, messages.c.display_order, func.row_number().over(partition_by=messages.c.display_order, order_by=(messages.c.active.desc(), messages.c.id.desc())).label('rank')).where(*eligible).subquery()
    page = select(ranked.c.id).where(ranked.c.rank == 1).order_by(ranked.c.display_order.desc() if latest else ranked.c.display_order)
    if limit is not None:
        page = page.limit(limit)
    if offset:
        page = page.offset(offset)
    return page

def _display_page(conn, scope, session_id, limit, offset, latest):
    page = display_ids(conn, scope, session_id, limit, offset, latest)
    from hermes_db.domains.sessions.postgres.support.message_codec import decoded_row
    return [decoded_row(row) for row in conn.execute(select(messages).where(repo.where(scope, [session_id]), messages.c.id.in_(page)).order_by(messages.c.display_order)).mappings()]

def _transcript_lineage_ids(conn, scope, session_id):
    from hermes_db.core.values import model_config
    row = session_repo.get_session(conn, scope, session_id)
    if row is None or not model_config(row.get('model_config')).get('_delegate_from'):
        return [session_id]
    return repo.resume_lineage(conn, scope, session_id)

def around(conn, scope, session_id, anchor_id, window):
    window = max(0, window)
    if repo.one(conn, scope, session_id, anchor_id) is None:
        return {'window': [], 'messages_before': 0, 'messages_after': 0}
    before = repo.select_rows(conn, scope, [session_id], messages.c.id <= anchor_id, limit=window + 1, latest=True)
    after = repo.select_rows(conn, scope, [session_id], messages.c.id > anchor_id, limit=window)
    return {'window': [codec._row_to_message_dict(row, warn_context='get_messages_around', summary_flag=False) for row in [*before, *after]], 'messages_before': len(before) - 1, 'messages_after': len(after)}

def valid_row_id(row_id):
    return isinstance(row_id, int) and (not isinstance(row_id, bool)) and (row_id > 0)

def _reaction_list(metadata):
    value = (metadata or {}).get('reactions')
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

def _reaction_row(conn, scope, session_id, row_id):
    ids = repo.resume_lineage(conn, scope, session_id)
    rows = repo.select_rows(conn, scope, ids, messages.c.id == row_id, repo.visible(), limit=1)
    return rows[0] if rows else None

def _valid_todo(row, prior, max_chars):
    if prior['role'] != 'assistant' or not row['content'] or len(row['content']) > max_chars:
        return False
    try:
        calls = json.loads(prior['tool_calls']) if prior['tool_calls'] else []
        if not isinstance(calls, list) or not any(_todo_call(call, row['tool_call_id']) for call in calls):
            return False
        data = json.loads(row['content'])
        if not isinstance(data, dict) or not isinstance(data.get('todos'), list):
            return False
        int(data.get('revision') or 0)
        return True
    except (ValueError, TypeError):
        return False

def _todo_call(call, call_id):
    if not isinstance(call, dict) or call.get('id') != call_id:
        return False
    function = call.get('function')
    if not isinstance(function, dict):
        return False
    if function.get('name') in ('todo_list', 'todo'):
        return True
    if function.get('name') != 'tool_call':
        return False
    arguments = function.get('arguments')
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    calls = arguments.get('calls') if isinstance(arguments, dict) else None
    return isinstance(calls, list) and any(isinstance(inner, dict) and inner.get('name') in ('todo_list', 'todo') for inner in calls)

def _copy_keys(row):
    return [row['display_identity'], *(('uid', uid) for uid in (row['message_uid'], *_uid_list(row['absorbed_message_uids'])) if uid)]

def _removed_todos(conn, scope, ids):
    columns = (messages.c.id, messages.c.display_identity, messages.c.message_uid, messages.c.absorbed_message_uids)
    rows = conn.execute(select(*columns).where(repo.where(scope, ids), messages.c.active == 0, messages.c.compacted == 0, messages.c.role == 'tool', messages.c.tool_name.in_(('todo_list', 'todo')))).mappings()
    removed = {}
    for row in rows:
        for key in _copy_keys(row):
            removed[key] = max(removed.get(key, 0), row['id'])
    return removed

class SessionMessages:

    def __init__(self, context, get_session):
        self._context = context
        self._get_session = get_session

    def append_message(self, session_id, role, content=None, tool_name=None, tool_calls=None, tool_call_id=None, token_count=None, finish_reason=None, reasoning=None, reasoning_content=None, reasoning_details=None, codex_reasoning_items=None, codex_message_items=None, platform_message_id=None, observed=False, effect_disposition=None, _compressed_summary=False, timestamp=None, api_content=None, display_kind=None, display_metadata=None, compression_lock_holder=None, turn_lease_holder=None, turn_lease_ttl_seconds=300.0, message_uid=None):
        self._context.assert_open()
        msg = dict(locals())
        msg.pop('self')
        return operations.append(self._context.transactions, self._context.scope, session_id, [msg], single=True, compression_lock_holder=compression_lock_holder, turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)

    def append_messages_batch(self, session_id, messages, compression_lock_holder=None, turn_lease_holder=None, chunk_rows=None, turn_lease_ttl_seconds=300.0):
        self._context.assert_open()
        if not messages:
            return 0
        if chunk_rows is not None:
            if chunk_rows <= 0:
                raise ValueError('chunk_rows must be positive')
            from hermes_db.domains.sessions.postgres.support.message_codec import codec
            from hermes_db.domains.sessions.codec import _parse_tool_calls
            index = {}
            for msg in messages:
                codec._stamp_tool_call_uids(msg, _parse_tool_calls(msg.get('tool_calls')), index)
            if len(messages) > chunk_rows:
                return sum(self.append_messages_batch(session_id, messages[start:start + chunk_rows], compression_lock_holder=compression_lock_holder, turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds) for start in range(0, len(messages), chunk_rows))
        return operations.append(self._context.transactions, self._context.scope, session_id, messages, compression_lock_holder=compression_lock_holder, turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)

    def replace_messages(self, session_id, messages, active_only=False, archive_dropped=False, reject_active_turn_lease=False):
        self._context.assert_open()
        operations.replace(self._context.transactions, self._context.scope, session_id, messages, active_only=active_only, archive_dropped=archive_dropped, reject_active_turn_lease=reject_active_turn_lease)

    def replace_messages_in_transaction(self, conn, session_id, messages, *, active_only=False, archive_dropped=False, reject_active_turn_lease=False, expected_active_ids=None):
        self._context.assert_open()
        operations.replace_on_connection(conn, self._context.scope, session_id, messages, active_only=active_only, archive_dropped=archive_dropped, reject_active_turn_lease=reject_active_turn_lease, expected_active_ids=expected_active_ids)

    def rewind_to_message(self, session_id, target_message_id, *, preserve_compaction_handoff=False, expected_active_ids=None, expected_target_content=None):
        with self._context.write() as conn:
            return operations.rewind(conn, self._context.scope, session_id, target_message_id, preserve_compaction_handoff=preserve_compaction_handoff, expected_active_ids=expected_active_ids, expected_target_content=expected_target_content)

    def transcript_cursor_state(self, session_id, through_id, lineage_ids=None):
        from sqlalchemy import or_
        with self._context.read() as conn:
            ids = list(lineage_ids) if lineage_ids else _transcript_lineage_ids(conn, self._context.scope, session_id)
            live = conn.scalar(select(func.count()).select_from(messages).where(repo.where(self._context.scope, ids), messages.c.active == 1, or_(messages.c.session_id != session_id, messages.c.id <= int(through_id))))
            inactive = conn.scalar(select(func.count()).select_from(messages).where(repo.where(self._context.scope, ids), messages.c.active == 0))
            edits = conn.scalar(select(func.coalesce(func.sum(sessions.c.transcript_edit_revision), 0)).where(sessions.c.store_id == self._context.scope.require_store_id(), sessions.c.id.in_(ids)))
            return (int(live), int(inactive), int(edits))

    def transcript_lineage_ids(self, session_id):
        with self._context.read() as conn:
            return _transcript_lineage_ids(conn, self._context.scope, session_id)

    def get_messages(self, session_id, include_inactive=False, include_compacted=False, limit=None, offset=0, latest=False, after_id=None, include_ancestors=False):
        if after_id is not None and (latest or offset or include_compacted or include_ancestors):
            raise ValueError('after_id is incompatible with latest/offset/compacted/ancestor paging')
        with self._context.read() as conn:
            ids = repo.resume_lineage(conn, self._context.scope, session_id) if include_ancestors else [session_id]
            if len(ids) > 1 or include_compacted:
                rows = _display_page(conn, self._context.scope, session_id, limit, offset, latest) if len(ids) == 1 and (not include_inactive) else None
                if rows is None:
                    rows = repo.display_set(conn, self._context.scope, ids) if include_compacted and (not include_inactive) else repo.select_rows(conn, self._context.scope, ids, *_active_filter(include_inactive, include_compacted))
                    rows = codec._dedupe_display_generations(rows, drop_removed=include_compacted and (not include_inactive))
                    rows = _page(rows, limit, offset, latest)
            else:
                conditions = _active_filter(include_inactive, include_compacted)
                if after_id is not None:
                    conditions.append(messages.c.id > after_id)
                rows = repo.select_rows(conn, self._context.scope, ids, *conditions, limit=limit, offset=offset, latest=latest)
        return [codec._row_to_message_dict(row, warn_context='get_messages', summary_flag=True) for row in rows]

    def get_messages_as_conversation(self, session_id, include_ancestors=False, include_inactive=False, repair_alternation=False, include_row_ids=False, include_compacted=False):
        with self._context.read() as conn:
            ids = repo.resume_lineage(conn, self._context.scope, session_id) if include_ancestors else [session_id]
            conditions = [] if include_compacted and (not include_inactive) else _active_filter(include_inactive, include_compacted)
            rows = repo.display_set(conn, self._context.scope, ids) if include_compacted and (not include_inactive) else repo.select_rows(conn, self._context.scope, ids, *conditions)
        if include_compacted:
            rows = codec._dedupe_display_generations(rows, drop_removed=not include_inactive)
        return codec._rows_to_conversation(rows, session_id=session_id, include_ancestors=include_ancestors, repair_alternation=repair_alternation, include_row_ids=include_row_ids, include_summary_markers=repair_alternation)

    def get_resume_conversations(self, session_id):
        with self._context.read() as conn:
            rows = repo.display_set(conn, self._context.scope, repo.resume_lineage(conn, self._context.scope, session_id))
        model = codec._rows_to_conversation([row for row in rows if row['session_id'] == session_id and row['active'] and (row['role'] != 'session_meta')], session_id=session_id, include_ancestors=False, repair_alternation=True, include_row_ids=True, include_summary_markers=True)
        display = codec._rows_to_conversation(codec._dedupe_display_generations(rows, drop_removed=True), session_id=session_id, include_ancestors=True, repair_alternation=False, include_row_ids=True)
        return (model, display)

    def get_active_message_ids(self, session_id):
        with self._context.read() as conn:
            return repo.active_ids(conn, self._context.scope, session_id)

    def get_active_message_watermark(self, session_id):
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            return conn.scalar(select(func.coalesce(func.max(messages.c.id), 0)).where(repo.where(self._context.scope, [session_id]), messages.c.active == 1))

    def conversation_revision(self, session_id, include_ancestors=False):
        with self._context.read() as conn:
            ids = repo.resume_lineage(conn, self._context.scope, session_id) if include_ancestors else [session_id]
            count, highest = conn.execute(select(func.count(), func.coalesce(func.max(messages.c.id), 0)).where(repo.where(self._context.scope, ids), messages.c.active == 1)).one()
            revision = conn.scalar(select(func.coalesce(func.sum(sessions.c.transcript_revision), 0)).where(sessions.c.store_id == self._context.scope.require_store_id(), sessions.c.id.in_(ids)))
        return (tuple(ids), count, highest, revision)

    def message_count(self, session_id=None):
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(messages).where(repo.where(self._context.scope, [session_id] if session_id else None)))

    def has_archived_messages(self, session_id):
        with self._context.read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self._context.scope, [session_id]), messages.c.active == 0).limit(1)) is not None

    def get_resume_message_count(self, session_id, *, tip_only=False):
        with self._context.read() as conn:
            return _resume_count(conn, self._context.scope, session_id, tip_only)

    def assert_resume_safe(self, session_id, max_messages=None, *, tip_only=False):
        if max_messages is None:
            with self._context.profile.activate():
                max_messages = self._context.transcript_limits.resume_limit()
        if max_messages < 0:
            raise ValueError('max_messages must be non-negative')
        if max_messages == 0:
            return 0
        with self._context.read() as conn:
            count = _resume_count(conn, self._context.scope, session_id, tip_only, max_messages + 1)
        if count > max_messages:
            raise self._context.transcript_limits.resume_error(count, max_messages, scope='in its tip segment' if tip_only else 'across its lineage')
        return count

    def get_ancestor_display_prefix(self, session_id):
        with self._context.read() as conn:
            rows = repo.display_set(conn, self._context.scope, repo.resume_lineage(conn, self._context.scope, session_id))
        rows = codec._dedupe_display_generations(rows, drop_removed=True)
        ancestor_ids = {row['id'] for row in rows if row['session_id'] != session_id}
        conversation = codec._rows_to_conversation(rows, session_id=session_id, include_ancestors=True, repair_alternation=False, include_row_ids=True)
        return [{key: value for key, value in msg.items() if key != '_row_id'} for msg in conversation if msg.get('_row_id') in ancestor_ids]

    def get_conversation_root(self, session_id):
        with self._context.read() as conn:
            return lineage_reads.get_conversation_root(conn, self._context.scope, session_id)

    def is_explicit_fork_child(self, session_id):
        row = self._get_session(session_id)
        return bool(row and codec._is_explicit_fork_child_row(row))

    def latest_message_row_id(self, session_id, *, role='user', offset=0, require_text=True):
        if not session_id or role not in {'user', 'assistant'} or offset < 0:
            return None
        with self._context.read() as conn:
            filters = [repo.where(self._context.scope, [session_id]), messages.c.active == 1, messages.c.role == role]
            if require_text:
                filters.append(func.trim(messages.c.search_content) != '')
            return conn.scalar(select(messages.c.id).where(*filters).order_by(messages.c.id.desc()).limit(1).offset(int(offset)))

    def latest_conversation_role(self, session_id):
        with self._context.read() as conn:
            return conn.scalar(select(messages.c.role).where(repo.where(self._context.scope, [session_id]), messages.c.active == 1, messages.c.role.not_in(('session_meta', 'system'))).order_by(messages.c.id.desc()).limit(1))

    def get_message_role(self, session_id, row_id):
        with self._context.read() as conn:
            return conn.scalar(select(messages.c.role).where(repo.where(self._context.scope, [session_id]), messages.c.id == int(row_id), messages.c.active == 1))

    def get_messages_around(self, session_id, around_message_id, window=5):
        with self._context.read() as conn:
            return around(conn, self._context.scope, session_id, around_message_id, window)

    def has_platform_message_id(self, session_id, platform_message_id):
        with self._context.read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self._context.scope, [session_id]), messages.c.platform_message_id == platform_message_id).limit(1)) is not None

    def has_gateway_input_owner(self, session_id, owner):
        with self._context.read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self._context.scope, [session_id]), messages.c.role == 'user', messages.c.observed == 0, repo.visible(), display_value(messages.c.display_metadata, 'gateway_input_owner') == query_token(owner)).limit(1)) is not None

    def latest_conversation_boundary(self, session_key, source):
        with self._context.read() as conn:
            return lineage_reads.latest_conversation_boundary(conn, self._context.scope, session_key, source)

    def find_pr_url_messages(self, session_ids):
        with self._context.read() as conn:
            rows = repo.select_rows(conn, self._context.scope, [sid for sid in session_ids if sid], messages.c.role == 'tool', messages.c.search_content.contains('/pull/', autoescape=True))
        return [{'session_id': row['session_id'], 'content': row['content']} for row in rows]

    def display_message_count(self, session_id):
        from hermes_db.domains.sessions.postgres.messages import display_ids
        with self._context.read() as conn:
            return conn.scalar(select(func.count()).select_from(display_ids(conn, self._context.scope, session_id).subquery()))

    def resolve_resume_session_id(self, session_id):
        with self._context.read() as conn:
            return lineage_reads.resolve_resume_session_id(conn, self._context.scope, session_id)

    def set_message_api_content(self, session_id, row_id, content, api_content):
        from hermes_db.domains.sessions.codec import _scrub_surrogates
        if not session_id or not valid_row_id(row_id):
            return 0
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            return self._backfill_api_content(conn, session_id, row_id, content, _scrub_surrogates(api_content))

    def _backfill_api_content(self, conn, session_id, row_id, content, api_content):
        from hermes_db.domains.sessions.postgres.support.message_codec import content_to_bytes
        row = repo.one(conn, self._context.scope, session_id, row_id)
        if not row or row['role'] != 'user' or (not row['active']) or (content_to_bytes(row['content']) != content_to_bytes(codec._encode_content(content))):
            return 0
        return repo.update_row(conn, self._context.scope, session_id, row_id, {'api_content': api_content})

    def set_latest_user_api_content(self, session_id, content, api_content):
        from hermes_db.domains.sessions.codec import _scrub_surrogates
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            row_id = conn.scalar(select(messages.c.id).where(repo.where(self._context.scope, [session_id]), messages.c.active == 1, messages.c.role == 'user').order_by(messages.c.id.desc()).limit(1))
            return self._backfill_api_content(conn, session_id, row_id, content, _scrub_surrogates(api_content)) if row_id else 0

    def set_user_message_content(self, session_id, row_id, content, display_metadata=None):
        if not session_id or not valid_row_id(row_id):
            return 0
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            row = repo.one(conn, self._context.scope, session_id, row_id)
            if not row or not row['active'] or row['role'] != 'user':
                return 0
            values = {'content': codec._encode_content(content)}
            if display_metadata is not None:
                from hermes_db.domains.sessions.postgres.support.message_codec import merge_display_metadata
                current = codec._decode_display_metadata(row['display_metadata'])
                patch = codec._decode_display_metadata(codec._encode_display_metadata(display_metadata)) or {}
                merged = merge_display_metadata(current, patch)
                values.update(api_content=None, display_metadata=codec._encode_display_metadata(merged))
            return repo.update_row(conn, self._context.scope, session_id, row_id, values)

    def deactivate_message(self, session_id, row_id):
        if not session_id or not valid_row_id(row_id):
            return 0
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            return repo.update_row(conn, self._context.scope, session_id, row_id, {'active': 0})

    def deactivate_messages_by_display_kind(self, session_id, display_kind):
        if not session_id or not display_kind:
            return 0
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            result = conn.execute(messages.update().where(repo.where(self._context.scope, [session_id]), messages.c.active == 1, messages.c.display_kind == display_kind).values(active=0))
            if result.rowcount:
                repo.bump_revision(conn, self._context.scope, session_id)
            return result.rowcount

    def resolve_active_row_id(self, session_id, row_id):
        if not session_id or not valid_row_id(row_id):
            return None
        with self._context.read() as conn:
            row = repo.one(conn, self._context.scope, session_id, row_id)
            if not row:
                return None
            if row['active']:
                return row_id
            from hermes_db.domains.sessions.postgres.support.message_codec import content_to_bytes
            clones = list(conn.execute(select(messages.c.id).where(repo.where(self._context.scope, [session_id]), messages.c.active == 1, messages.c.id > row_id, messages.c.role == row['role'], messages.c.content.is_not_distinct_from(content_to_bytes(row['content'])), messages.c.timestamp == row['timestamp']).limit(2)).scalars())
            return clones[0] if len(clones) == 1 else None

    def clear_messages(self, session_id):
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            conn.execute(messages.delete().where(repo.where(self._context.scope, [session_id])))
            session_repo.update_session(conn, self._context.scope, session_id, {'message_count': 0, 'tool_call_count': 0})
            repo.bump_revision(conn, self._context.scope, session_id)

    def set_latest_matching_message_display_kind(self, session_id, *, role, content, display_kind, display_metadata=None):
        if not session_id or not content or (not display_kind):
            return False
        from hermes_db.domains.sessions.postgres.support.message_codec import content_to_bytes
        from hermes_db.domains.sessions.codec import _scrub_surrogates
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            row_id = conn.scalar(select(messages.c.id).where(repo.where(self._context.scope, [session_id]), messages.c.role == role, messages.c.content == content_to_bytes(codec._encode_content(content)), messages.c.active == 1).order_by(messages.c.id.desc()).limit(1))
            if row_id is None:
                return False
            repo.update_row(conn, self._context.scope, session_id, row_id, {'display_kind': _scrub_surrogates(display_kind), 'display_metadata': codec._encode_display_metadata(display_metadata)})
            return True

    def set_message_reaction(self, session_id, message_row_id, emoji, *, author='user'):
        if not session_id or message_row_id is None:
            return None
        from hermes_db.domains.sessions.codec import _scrub_surrogates
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            row = _reaction_row(conn, self._context.scope, session_id, message_row_id)
            if row is None:
                return None
            metadata = codec._decode_display_metadata(row['display_metadata']) or {}
            existing = _reaction_list(metadata)
            reactions = [item for item in existing if item.get('author') != author]
            previous = next((item for item in existing if item.get('author') == author), None)
            if emoji and (previous is None or previous.get('emoji') != emoji):
                reactions.append({'emoji': _scrub_surrogates(emoji), 'author': author, 'at': time.time()})
            if reactions:
                metadata['reactions'] = reactions
            else:
                metadata.pop('reactions', None)
            repo.update_row(conn, self._context.scope, row['session_id'], message_row_id, {'display_metadata': codec._encode_display_metadata(metadata)})
            return reactions

    def get_message_reactions(self, session_id, message_row_id):
        if not session_id or message_row_id is None:
            return []
        with self._context.read() as conn:
            row = _reaction_row(conn, self._context.scope, session_id, message_row_id)
            return _reaction_list(codec._decode_display_metadata(row['display_metadata'])) if row else []

    def take_unseen_reactions(self, session_id, *, author='user'):
        if not session_id:
            return []
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            ids = repo.resume_lineage(conn, self._context.scope, session_id)
            rows = repo.select_rows(conn, self._context.scope, ids, repo.visible(), display_value(messages.c.display_metadata, 'reactions').is_not(None))
            pending = []
            for row in rows:
                metadata = codec._decode_display_metadata(row['display_metadata']) or {}
                changed = False
                for reaction in _reaction_list(metadata):
                    if reaction.get('author') != author or reaction.get('seen'):
                        continue
                    reaction['seen'] = True
                    changed = True
                    content = codec._decode_content(row['content'])
                    pending.append({'row_id': row['id'], 'role': row['role'], 'emoji': reaction.get('emoji') or '', 'text': content if isinstance(content, str) else ''})
                if changed:
                    repo.update_row(conn, self._context.scope, row['session_id'], row['id'], {'display_metadata': codec._encode_display_metadata(metadata)})
            return pending

    def append_delegation_delivery(self, session_id, content, metadata):
        if not metadata.get('delegation_id'):
            raise ValueError('Delegation delivery requires a stable delegation_id')
        kind = 'hidden' if metadata.get('presentation_suppressed') else 'async_delegation_complete'
        return self._append_result(session_id, content, kind, metadata, {'delegation_id': metadata['delegation_id'], 'delivery_notice': metadata.get('delivery_notice', '')})

    def append_completion_note(self, session_id, admission_id, content, display_kind, metadata):
        return self._append_result(session_id, content, display_kind, {**metadata, 'completion_admission': admission_id}, {'completion_admission': admission_id})

    def _append_result(self, session_id, content, display_kind, metadata, identity):
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            ids = repo.resume_lineage(conn, self._context.scope, session_id)
            conditions = [repo.where(self._context.scope, ids)]
            for key, value in identity.items():
                column = display_value(messages.c.display_metadata, key)
                if key == 'delivery_notice':
                    column = func.coalesce(column, query_token(''))
                conditions.append(column == query_token(value))
            if 'delegation_id' in identity:
                conditions.append(messages.c.display_kind.in_(('async_delegation_complete', 'hidden')))
            row_id = conn.scalar(select(messages.c.id).where(*conditions).limit(1))
            if row_id is not None:
                return row_id
            transcript_guards.check(conn, self._context.scope, session_id, reject_active_turn_lease=True)
            batch = [{'role': 'user', 'content': content, 'display_kind': display_kind, 'display_metadata': metadata}]
            operations.insert_rows(conn, self._context.scope, session_id, batch)
            repo.bump_counters(conn, self._context.scope, session_id, 1, 0)
            return batch[0]['_row_id']

    def get_latest_todo_result(self, session_id, *, max_chars=None):
        if not session_id:
            return None
        if max_chars is None:
            from tools.todo_tool import MAX_TODO_RESULT_CHARS
            max_chars = MAX_TODO_RESULT_CHARS
        with self._context.read() as conn:
            ids = repo.resume_lineage(conn, self._context.scope, session_id)
            removed = _removed_todos(conn, self._context.scope, ids)
            for sid in reversed(ids):
                before_id = 2 ** 63 - 1
                while True:
                    rows = repo.select_rows(conn, self._context.scope, [sid], messages.c.role == 'tool', repo.visible(), messages.c.tool_name.in_(('todo_list', 'todo')), messages.c.id < before_id, func.length(messages.c.content) <= max_chars * 4 + 1, limit=100, latest=True)
                    if not rows:
                        break
                    for row in reversed(rows):
                        if not row['tool_call_id'] or any(removed.get(key, 0) > row['id'] for key in _copy_keys(row)):
                            continue
                        prior = repo.select_rows(conn, self._context.scope, [sid], messages.c.id < row['id'], repo.visible(), messages.c.role.in_(('assistant', 'user', 'system')), limit=1, latest=True)
                        if prior and _valid_todo(row, prior[0], max_chars):
                            return row['content']
                    before_id = rows[0]['id']
        return None
