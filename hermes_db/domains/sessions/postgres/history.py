"""SessionHistory: explicit scoped session history operations sharing one resource context."""
from hermes_db.domains.sessions.postgres.operations import compression, compression_state as state, rewrites
from hermes_db.domains.sessions.postgres.queries import lineage_reads, sessions, messages as transcript_pages_repo, sessions as session_repo, retirement, sessions as lineage_reads_repo, messages as recall_views_repo, search_context
import time
from hermes_db.tables.conversations import sessions as table, messages
from copy import deepcopy
from agent.message_metadata import DB_ROW_SNAPSHOT
from hermes_state_rewind import plan_user_turn_rewind, rewind_user_turn, RewindPlan, RewindOutcome
from typing import Any, Optional
from sqlalchemy import and_, func, or_, select
from hermes_db.domains.sessions.postgres.support.message_codec import codec, content_to_bytes, decoded_row
from hermes_db.domains.sessions.postgres.messages import display_ids
from hermes_db.core.values import model_config
from hermes_db.domains.sessions.postgres.messages import around
from hermes_db.backends.postgresql.search import statement
from hermes_db.domains.sessions.postgres.support.search_query import parse_query
from hermes_db.domains.sessions.search_rules import SearchRules, search_sessions_by_id

def _holder(table):
    body = func.encode(table.c.content, 'escape')
    return and_(table.c.role.in_(['user', 'assistant']), or_(table.c._compressed_summary == 1, body.contains('[CONTEXT COMPACTION', autoescape=True), body.contains('[CONTEXT SUMMARY]', autoescape=True)))

def _handoff(row):
    return codec._row_to_message_dict(row, warn_context='session.transcript', summary_flag=True)

def _page(conn, scope, segment, count, latest, position):
    ids = display_ids(conn, scope, segment, limit=count, latest=latest, after=position)
    return [decoded_row(row) for row in conn.execute(select(messages).where(transcript_pages_repo.where(scope, [segment]), messages.c.id.in_(ids)).order_by(messages.c.display_order)).mappings()]

def _cursor_slot(conn, scope, segment, durable):
    row = conn.execute(select(messages.c.display_identity, messages.c.display_order, messages.c.active, messages.c.compacted, messages.c.message_uid).where(transcript_pages_repo.where(scope, [segment]), messages.c.id == durable)).mappings().one_or_none()
    if row is None:
        return None
    if row['display_identity'] is not None:
        copy = conn.scalar(select(messages.c.display_order).where(transcript_pages_repo.where(scope, [segment]), messages.c.display_identity == row['display_identity'], transcript_pages_repo.visible(), messages.c.display_order.is_not(None)).order_by(messages.c.active.desc(), messages.c.id.desc()).limit(1))
        if copy is not None:
            return copy
    if row['message_uid']:
        carrier = conn.scalar(select(messages.c.display_order).where(transcript_pages_repo.where(scope, [segment]), messages.c.message_uid == row['message_uid'], messages.c.active == 1, messages.c._compressed_summary == 1, messages.c.display_order.is_not(None)).order_by(messages.c.id.desc()).limit(1))
        if carrier is not None:
            return carrier
    return row['display_order'] if row['active'] == 1 or row['compacted'] == 1 else None

def _durable_firsts(conn, scope, segment, rows):
    identities = {row['display_identity'] for row in rows if row['display_identity'] is not None}
    stamps = {row['timestamp'] for row in rows if row['timestamp'] is not None}
    by_identity = dict(conn.execute(select(messages.c.display_identity, func.min(messages.c.id)).where(transcript_pages_repo.where(scope, [segment]), messages.c.active == 0, messages.c.compacted == 0, messages.c.timestamp.in_(stamps), messages.c.display_identity.in_(identities)).group_by(messages.c.display_identity)).all()) if identities and stamps else {}
    carriers = [row for row in rows if row['_compressed_summary'] and row['message_uid'] and (row['timestamp'] is not None)]
    by_uid = dict(conn.execute(select(messages.c.message_uid, func.min(messages.c.id)).where(transcript_pages_repo.where(scope, [segment]), messages.c.active == 0, messages.c.timestamp.in_({row['timestamp'] for row in carriers}), messages.c.message_uid.in_({row['message_uid'] for row in carriers})).group_by(messages.c.message_uid)).all()) if carriers else {}
    return {row['id']: min(row['display_order'], by_identity.get(row['display_identity'], row['id']), by_uid.get(row['message_uid'], row['id']) if row['_compressed_summary'] else row['id']) for row in rows}

def _bookends(conn, scope, sid, rows, bookend, keep_roles):
    if bookend <= 0:
        return ([], [])
    conditions = [func.length(messages.c.content) > 1, func.substr(messages.c.content, 1, 2) != b'T\x00']
    if keep_roles is not None:
        conditions.append(messages.c.role.in_(keep_roles))
    start = recall_views_repo.select_rows(conn, scope, [sid], *conditions, messages.c.id < rows[0]['id'], limit=bookend)
    end = recall_views_repo.select_rows(conn, scope, [sid], *conditions, messages.c.id > rows[-1]['id'], limit=bookend, latest=True)
    return tuple([codec._row_to_message_dict(row, warn_context='get_anchored_view', summary_flag=False) for row in part] for part in (start, end))

def _find(conn, scope, plan, options):
    route = 'substring' if plan.cjk else 'fts'
    matches = [dict(row) for row in conn.execute(statement(scope, plan, route=route, **options)).mappings()]
    if not matches and (not plan.cjk) and all(len(term[0]) >= 3 for term in plan.terms):
        matches = [dict(row) for row in conn.execute(statement(scope, plan, route='substring', **options)).mappings()]
    if not matches and plan.relaxed and ('tool' not in (options.get('role_filter') or ())):
        relaxed = parse_query(plan.relaxed)
        matches = [dict(row) for row in conn.execute(statement(scope, relaxed, **options)).mappings()]
    return matches

class SessionHistory:

    def __init__(self, context, get_active_message_ids, get_messages_as_conversation, list_sessions_rich, rewind_to_message):
        self._context = context
        self._get_active_message_ids = get_active_message_ids
        self._get_messages_as_conversation = get_messages_as_conversation
        self._list_sessions_rich = list_sessions_rich
        self._rewind_to_message = rewind_to_message

    def publish_compression_child(self, *, parent_session_id, child_session_id, source, messages, model=None, model_config=None, system_prompt=None, cwd=None, profile_name=None, compression_lock_holder=None, require_compression_lease=True, require_lease_refresh=False, lease_ttl_seconds=300.0, watermark=None, watermark_ceiling=None):
        from hermes_db.domains.sessions.postgres.operations.compression_publish import publish
        self._context.assert_open()
        publish(self._context.transactions, self._context.scope, parent_session_id=parent_session_id, child_session_id=child_session_id, source=source, messages=messages, model=model, model_config=model_config, system_prompt=system_prompt, cwd=cwd, profile_name=profile_name, own_profile=self._context.own_profile, compression_lock_holder=compression_lock_holder, require_compression_lease=require_compression_lease, require_lease_refresh=require_lease_refresh, lease_ttl_seconds=lease_ttl_seconds, watermark=watermark, watermark_ceiling=watermark_ceiling)

    def get_compression_chain(self, session_id):
        with self._context.read() as conn:
            return lineage_reads.get_compression_chain(conn, self._context.scope, session_id)

    def get_compression_tip(self, session_id):
        with self._context.read() as conn:
            return lineage_reads.get_compression_tip(conn, self._context.scope, session_id)

    def archive_and_compact(self, session_id, compacted_messages, model_config_patch=None, watermark=None, lock_holder=None, tail_count=0, carried_messages=None, covered_ids=None, unresolved_held=None, held_for_cas=None):
        self._context.assert_open()
        return compression.compact(self._context.transactions, self._context.scope, session_id, compacted_messages, model_config_patch=model_config_patch, watermark=watermark, lock_holder=lock_holder, tail_count=tail_count, carried_messages=carried_messages, covered_ids=covered_ids, unresolved_held=unresolved_held, held_for_cas=held_for_cas)

    def rewritten_held_row_ids(self, session_id, held):
        from hermes_db.domains.sessions.postgres.support.compression_coverage import Coverage
        from hermes_db.domains.sessions.postgres.queries import messages
        from hermes_db.tables.conversations import messages as table
        with self._context.read() as conn:
            rows = messages.select_rows(conn, self._context.scope, [session_id], table.c.active == 1)
            return Coverage(rows).mismatches(held)

    def held_row_mismatches(self, conn, session_id, held):
        from hermes_db.domains.sessions.postgres.support.compression_coverage import Coverage
        from hermes_db.domains.sessions.postgres.queries import messages
        from hermes_db.tables.conversations import messages as table
        return Coverage(messages.select_rows(conn, self._context.scope, [session_id], table.c.active == 1)).mismatches(held)

    def get_compression_failure_cooldown_row(self, session_id):
        with self._context.read() as conn:
            return state.cooldown_row(conn, self._context.scope, session_id)

    def get_compression_failure_cooldown(self, session_id):
        row = self.get_compression_failure_cooldown_row(session_id)
        deadline, now = (row['cooldown_until'], time.time())
        if deadline is None or deadline <= now:
            return None
        return {'cooldown_until': deadline, 'remaining_seconds': deadline - now, 'error': row['error']}

    def record_compression_failure_cooldown(self, session_id, cooldown_until, error=None):
        with self._context.write() as conn:
            state.record_cooldown(conn, self._context.scope, session_id, cooldown_until, error)

    def restore_compression_failure_cooldown_row(self, session_id, snapshot):
        with self._context.write() as conn:
            state.restore_cooldown(conn, self._context.scope, session_id, snapshot)

    def clear_compression_failure_cooldown(self, session_id):
        self.restore_compression_failure_cooldown_row(session_id, {'session_exists': True, 'cooldown_until': None, 'error': None})

    def _compression_number(self, session_id, column, cast=int):
        with self._context.read() as conn:
            row = sessions.raw_session(conn, self._context.scope, session_id)
            return max(cast(0), cast(row[column] or 0)) if row else cast(0)

    def _set_compression_number(self, session_id, column, value):
        with self._context.write() as conn:
            if sessions.lock_session(conn, self._context.scope, session_id) is not None:
                sessions.update_session(conn, self._context.scope, session_id, {column: value})

    def get_compression_fallback_streak(self, session_id):
        return self._compression_number(session_id, 'compression_fallback_streak')

    def set_compression_fallback_streak(self, session_id, streak):
        self._set_compression_number(session_id, 'compression_fallback_streak', max(0, int(streak)))

    def get_compression_ineffective_count(self, session_id):
        return self._compression_number(session_id, 'compression_ineffective_count')

    def set_compression_ineffective_count(self, session_id, count):
        self._set_compression_number(session_id, 'compression_ineffective_count', max(0, int(count)))

    def get_compression_overload_streak(self, session_id):
        return self._compression_number(session_id, 'compression_overload_streak')

    def set_compression_overload_streak(self, session_id, streak):
        self._set_compression_number(session_id, 'compression_overload_streak', max(0, int(streak)))

    def increment_compression_overload_streak(self, session_id):
        with self._context.write() as conn:
            if sessions.lock_session(conn, self._context.scope, session_id) is None:
                return None
            return conn.scalar(table.update().where(sessions.where_session(self._context.scope, session_id)).values(compression_overload_streak=table.c.compression_overload_streak + 1).returning(table.c.compression_overload_streak))

    def get_compression_recovery_deadline(self, session_id):
        return self._compression_number(session_id, 'compression_recovery_deadline', float)

    def set_compression_recovery_deadline(self, session_id, deadline):
        try:
            normalized = max(0.0, float(deadline or 0))
        except (TypeError, ValueError):
            normalized = 0.0
        self._set_compression_number(session_id, 'compression_recovery_deadline', normalized or None)

    def reopen_if_explicitly_closed(self, session_id, *, provenance, patience_s=None):
        self._context.assert_open()
        with self._context.transactions.write(lock_timeout=patience_s) as conn:
            return state.reopen(conn, self._context.scope, session_id)

    def reopen_orphaned_compression_session(self, session_id):
        with self._context.write() as conn:
            return state.reopen(conn, self._context.scope, session_id, orphan=True)

    def find_live_compression_child(self, parent_session_id):
        with self._context.read() as conn:
            rows = state.children(conn, self._context.scope, parent_session_id, live_only=True)
            return sessions.get_session(conn, self._context.scope, rows[0]['id']) if len(rows) == 1 else None

    def finalize_orphaned_compression_sessions(self):
        with self._context.write() as conn:
            return state.finalize_orphans(conn, self._context.scope)

    def get_compression_lineage(self, session_id):
        with self._context.read() as conn:
            return lineage_reads.get_compression_lineage(conn, self._context.scope, session_id)

    def retain_refused_turn_for_display(self, session_id, *, notice, boundary_row_id=None):
        from agent.context_compressor import split_user_originated_turn
        from agent.turn_failure_copy import CONTENT_REFUSED_DISPLAY_KIND, CONTENT_REFUSED_METADATA_KEY
        from hermes_db.domains.sessions.postgres.support.message_codec import codec
        from hermes_db.domains.sessions.postgres.operations.messages import rewind
        from hermes_db.domains.sessions.postgres.queries import messages as repo
        from hermes_state_rewind import RewindTargetUnavailableError
        with self._context.read() as conn:
            row = repo.one(conn, self._context.scope, session_id, boundary_row_id) if isinstance(boundary_row_id, int) and boundary_row_id > 0 else None
            if row and row['role'] == 'user' and row['active']:
                target = row['id']
                handoff, _ = split_user_originated_turn(codec._row_to_message_dict(row, warn_context='refusal', summary_flag=True))
                preserve = handoff is not None
                expected = repo.active_ids(conn, self._context.scope, session_id)
        if not row or row['role'] != 'user' or (not row['active']):
            try:
                plan = self.plan_user_turn_rewind(session_id, -1)
            except RewindTargetUnavailableError:
                return False
            target, preserve, expected = (plan.target_row_id, plan.scaffold is not None, plan.expected_active_ids)
        with self._context.write() as conn:
            rewind(conn, self._context.scope, session_id, target, preserve_compaction_handoff=preserve, expected_active_ids=expected)
            row = repo.one(conn, self._context.scope, session_id, target)
            metadata = codec._decode_display_metadata(row['display_metadata']) or {}
            metadata[CONTENT_REFUSED_METADATA_KEY] = {'notice': notice}
            repo.update_row(conn, self._context.scope, session_id, target, {'compacted': 1, 'display_kind': CONTENT_REFUSED_DISPLAY_KIND, 'display_metadata': codec._encode_display_metadata(metadata)})
        return True

    def rewrite_pruned_rows(self, session_id, changes, *, model_config_patch=None, turn_lease_holder=None, turn_lease_ttl_seconds=300):
        work = deepcopy(changes)
        with self._context.write() as conn:
            count = rewrites.prune(conn, self._context.scope, session_id, work, model_config_patch=model_config_patch, turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)
        for (_, replacement), (_, committed) in zip(changes, work):
            if DB_ROW_SNAPSHOT in committed:
                replacement[DB_ROW_SNAPSHOT] = committed[DB_ROW_SNAPSHOT]
        return count

    def rewind_user_turn(self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False, adopt_row_ids: bool=False) -> RewindOutcome:
        """Rewind the active transcript to just before user turn ``user_ordinal`` (0 = oldest; negative counts
            back from the newest and clamps to the oldest, so ``-n`` is ``/undo n``). ``warm_history`` (CLI/TUI):
            the in-memory view must have the same user turns and the same live target text as the durable
            transcript, else ``RuntimeError`` and nothing changes; its (richer) prefix is what gets installed.
            ``require_retryable``: the live payload must be losslessly replayable as text (``ValueError`` from
            :func:`retryable_user_text` before any write). ``require_composite``: the target must be a compaction
            carrier. ``adopt_row_ids`` (TUI): copy durable ``_row_id`` identities onto the installed warm prefix so
            clients can address follow-ups by row; the CLI leaves its history shape alone. Out-of-range /
            wrong-shape targets raise :class:`RewindTargetUnavailableError`."""
        return rewind_user_turn(self.plan_user_turn_rewind, self._rewind_to_message, session_id, user_ordinal, warm_history=warm_history, require_retryable=require_retryable, require_composite=require_composite, adopt_row_ids=adopt_row_ids)

    def plan_user_turn_rewind(self, session_id: str, user_ordinal: int, *, warm_history: Optional[list[dict[str, Any]]]=None, require_retryable: bool=False, require_composite: bool=False) -> RewindPlan:
        """Every read and check :meth:`rewind_user_turn` makes before its write, with no write: the
            gateway ``/retry`` commits the planned rewind inside its re-send's admission transaction
            (``rewind_in_transaction`` with the plan's pins), so a refused re-send leaves it unapplied."""
        return plan_user_turn_rewind(self._get_messages_as_conversation, self._get_active_message_ids, session_id, user_ordinal, warm_history=warm_history, require_retryable=require_retryable, require_composite=require_composite)

    def _resume_lineage_ids(self, session_id):
        with self._context.read() as conn:
            return transcript_pages_repo.resume_lineage(conn, self._context.scope, session_id)

    def _rows_to_conversation(self, rows, **kwargs):
        return codec._rows_to_conversation(rows, **kwargs)

    def _dedupe_display_generations(self, rows, **kwargs):
        return codec._dedupe_display_generations(rows, **kwargs)

    def _fetch_conversation_rows(self, session_ids, extra_where='', *, with_session_id=False, with_compacted=False):
        if extra_where:
            raise ValueError('Core transcript reads do not accept SQL fragments')
        with self._context.read() as conn:
            return transcript_pages_repo.display_set(conn, self._context.scope, session_ids) if with_compacted else transcript_pages_repo.select_rows(conn, self._context.scope, session_ids, messages.c.active == 1)

    def _ensure_display_order(self, session_id):
        if self.transcript_display_index_complete(session_id):
            return True
        with self._context.write() as conn:
            session_repo.lock_session(conn, self._context.scope, session_id)
            transcript_pages_repo.reconcile_orders(conn, self._context.scope, session_id)
        return True

    def transcript_display_index_complete(self, segment):
        with self._context.read() as conn:
            return conn.scalar(select(messages.c.id).where(transcript_pages_repo.where(self._context.scope, [segment]), transcript_pages_repo.visible(), or_(messages.c.display_order.is_(None), messages.c.display_identity.is_(None))).limit(1)) is None

    def transcript_segment_page(self, segment, *, latest, after, count, inclusive=False):
        with self._context.read() as conn:
            position = None
            if after is not None:
                found = _cursor_slot(conn, self._context.scope, segment, after[1])
                position = after[0] if found is None else found
                if inclusive:
                    position += 1 if latest else -1
            rows = _page(conn, self._context.scope, segment, count, latest, position)
            firsts = _durable_firsts(conn, self._context.scope, segment, rows)
            before = _page(conn, self._context.scope, segment, 1, True, min(row['display_order'] for row in rows)) if rows else []
            return (rows, firsts, before)

    def transcript_tool_calls_before(self, segment_ids, before_id, limit=16):
        with self._context.read() as conn:
            return [tuple(row) for row in conn.execute(select(messages.c.tool_calls, messages.c.tool_call_uids).where(transcript_pages_repo.where(self._context.scope, segment_ids), messages.c.role == 'assistant', messages.c.tool_calls.is_not(None), messages.c.id < before_id).order_by(messages.c.id.desc()).limit(limit))]

    def transcript_handoff_rows(self, shown_ids, segment_ids):
        if not shown_ids:
            return {}
        with self._context.read() as conn:
            shown = conn.execute(select(messages.c.id, messages.c.message_uid, and_(messages.c.session_id.in_(segment_ids), _holder(messages)).label('holds')).where(transcript_pages_repo.where(self._context.scope), messages.c.id.in_(shown_ids))).mappings().all()
            uids = {row['message_uid'] for row in shown if row['message_uid']}
            copies = transcript_pages_repo.select_rows(conn, self._context.scope, segment_ids, messages.c.message_uid.in_(uids), messages.c.id < max(shown_ids), _holder(messages)) if uids else []
            holders = {row['id']: row for row in transcript_pages_repo.select_rows(conn, self._context.scope, segment_ids, messages.c.id.in_([row['id'] for row in shown if row['holds']]))}
        found = {}
        by_uid = {}
        for row in copies:
            by_uid.setdefault(row['message_uid'], []).append(row)
        for row in shown:
            held = [copy for copy in by_uid.get(row['message_uid'], ()) if copy['id'] < row['id']]
            if row['id'] in holders:
                held.append(holders[row['id']])
            if held:
                found[row['id']] = [_handoff(copy) for copy in held]
        return found

    def transcript_handoffs_shown_before(self, segment, before, handoffs):
        handoffs = list(handoffs)
        uids = {uid for uid, _ in handoffs if uid}
        contents = [content_to_bytes(codec._encode_content(content)) for uid, content in handoffs if not uid and isinstance(content, (str, list, dict))]
        if not uids and (not contents):
            return []
        shown = messages.alias('handoff_shown')
        held = select(1).where(shown.c.store_id == messages.c.store_id, shown.c.session_id == messages.c.session_id, or_(shown.c.id == messages.c.id, and_(messages.c.message_uid.is_not(None), messages.c.message_uid != '', shown.c.message_uid == messages.c.message_uid, shown.c.id > messages.c.id)), shown.c.id.in_(display_ids(None, self._context.scope, segment, latest=True, after=before))).correlate(messages).exists()
        match = or_(messages.c.message_uid.in_(uids), and_(or_(messages.c.message_uid.is_(None), messages.c.message_uid == ''), messages.c.content.in_(contents)))
        with self._context.read() as conn:
            rows = transcript_pages_repo.select_rows(conn, self._context.scope, [segment], match, _holder(messages), held)
        return [_handoff(row) for row in rows]

    @staticmethod
    def _is_explicit_fork_child_row(row, *, include_reset=False):
        if row.get('source') == 'tool':
            return True
        cfg = model_config(row.get('model_config'))
        names = ('_branched_from', '_delegate_from', '_reset_from') if include_reset else ('_branched_from', '_delegate_from')
        markers = [cfg.get(name) for name in names]
        parent = row.get('parent_session_id')
        return parent in markers if parent else any(marker is not None for marker in markers)

    def get_tool_rotation_root(self, session_id):
        with self._context.read() as conn:
            return lineage_reads.get_tool_rotation_root(conn, self._context.scope, session_id)

    def delegate_descendant_ids(self, session_id):
        with self._context.read() as conn:
            seeds, seen, current = ([], set(), session_id)
            while current and current not in seen:
                seen.add(current)
                row = lineage_reads_repo.raw_session(conn, self._context.scope, current)
                cfg = model_config(row['model_config']) if row else {}
                if cfg.get('_delegate_from'):
                    break
                seeds.append(current)
                if not row or cfg.get('_branched_from'):
                    break
                current = row['parent_session_id']
            found, frontier = ([], seeds)
            while frontier:
                children = [sid for sid in retirement.delegate_children(conn, self._context.scope, frontier) if sid not in found]
                frontier = [sid for sid in retirement.compression_members(conn, self._context.scope, children) if sid not in found] if children else []
                found.extend(frontier)
            return found

    def get_anchored_view(self, session_id, around_message_id, window=5, bookend=3, keep_roles=('user', 'assistant')):
        with self._context.read() as conn:
            result = around(conn, self._context.scope, session_id, around_message_id, window)
            rows = result['window']
            start, end = _bookends(conn, self._context.scope, session_id, rows, max(0, bookend), keep_roles) if rows else ([], [])
        if keep_roles is not None:
            result['window'] = [row for row in rows if row['id'] == around_message_id or row['role'] in keep_roles]
        return {**result, 'bookend_start': start, 'bookend_end': end}

    def list_recent_user_messages(self, session_id, limit=20, include_inactive=False):
        from agent.context_compressor import ContextCompressor
        from agent.skill_commands import describe_skill_invocation
        from hermes_state_search import _flatten_text
        conditions = [messages.c.role == 'user', or_(messages.c.display_kind.is_(None), messages.c.display_kind.in_(('', 'steer')))]
        if not include_inactive:
            conditions.append(messages.c.active == 1)
        with self._context.read() as conn:
            rows = recall_views_repo.select_rows(conn, self._context.scope, [session_id], *conditions, limit=max(0, int(limit) * 2 + 5), latest=True)
        result = []
        for row in reversed(rows):
            if len(result) >= int(limit):
                break
            decoded = codec._decode_content(row['content'])
            if ContextCompressor._is_context_summary_content(decoded):
                continue
            preview = describe_skill_invocation(decoded) or decoded if isinstance(decoded, str) else _flatten_text(decoded)
            preview = ' '.join(preview.split())
            result.append({'id': row['id'], 'timestamp': row['timestamp'], 'preview': preview[:77] + '...' if len(preview) > 80 else preview})
        return result

    def search_messages(self, query, source_filter=None, exclude_sources=None, role_filter=None, limit=20, offset=0, sort=None, include_inactive=False, fields=None, after_ts=None, before_ts=None):
        result_fields = SearchRules._search_message_fields(fields)
        plan = parse_query(query)
        if not plan.groups or limit <= 0:
            return []
        options = dict(source_filter=source_filter, exclude_sources=exclude_sources, role_filter=role_filter, limit=limit, offset=offset, sort=sort, include_inactive=include_inactive, after_ts=after_ts, before_ts=before_ts)
        with self._context.read() as conn:
            matches = _find(conn, self._context.scope, plan, options)
            if result_fields is None or 'context' in result_fields:
                search_context.attach(conn, self._context.scope, matches)
        if result_fields is not None:
            return [{field: row[field] for field in result_fields} for row in matches]
        return matches

    def search_sessions_by_id(self, query: str, limit: int=20, include_archived: bool=True, source: str | None=None, sources: list[str] | None=None, exclude_sources: list[str] | None=None) -> list[dict[str, Any]]:
        """Search surfaced sessions by exact/prefix/substring session id. Also matches
            ``_lineage_root_id`` so an old compression root id resolves to the live continuation."""
        return search_sessions_by_id(self._list_sessions_rich, query, limit, include_archived, source, sources, exclude_sources)
