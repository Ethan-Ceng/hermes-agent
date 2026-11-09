"""Bounded Core reads for the stored transcript protocol."""

from sqlalchemy import and_, func, or_, select

from hermes_db.domains.sessions.postgres.support.message_codec import codec, content_to_bytes, decoded_row
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo
from hermes_db.domains.sessions.postgres.capabilities.message_reads import display_ids
from hermes_db.tables.conversations import messages


class SessionTranscriptPages:
    def _resume_lineage_ids(self, session_id):
        with self._read() as conn:
            return repo.resume_lineage(conn, self.scope, session_id)

    def _rows_to_conversation(self, rows, **kwargs):
        return codec._rows_to_conversation(rows, **kwargs)

    def _dedupe_display_generations(self, rows, **kwargs):
        return codec._dedupe_display_generations(rows, **kwargs)

    def _fetch_conversation_rows(self, session_ids, extra_where="", *, with_session_id=False, with_compacted=False):
        # The gateway's rotated-lineage read is guarded by its resume-size ceiling.
        if extra_where:
            raise ValueError("Core transcript reads do not accept SQL fragments")
        with self._read() as conn:
            return repo.display_set(conn, self.scope, session_ids) if with_compacted else repo.select_rows(
                conn, self.scope, session_ids, messages.c.active == 1)

    def _ensure_display_order(self, session_id):
        if self.transcript_display_index_complete(session_id):
            return True
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            repo.reconcile_orders(conn, self.scope, session_id)
        return True

    def transcript_display_index_complete(self, segment):
        with self._read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self.scope, [segment]), repo.visible(),
                or_(messages.c.display_order.is_(None), messages.c.display_identity.is_(None))).limit(1)) is None

    def transcript_segment_page(self, segment, *, latest, after, count, inclusive=False):
        with self._read() as conn:
            position = None
            if after is not None:
                found = _cursor_slot(conn, self.scope, segment, after[1])
                position = after[0] if found is None else found
                if inclusive:
                    position += 1 if latest else -1
            rows = _page(conn, self.scope, segment, count, latest, position)
            firsts = _durable_firsts(conn, self.scope, segment, rows)
            before = _page(conn, self.scope, segment, 1, True, min(row['display_order'] for row in rows)) if rows else []
            return rows, firsts, before

    def transcript_tool_calls_before(self, segment_ids, before_id, limit=16):
        with self._read() as conn:
            return [tuple(row) for row in conn.execute(select(messages.c.tool_calls, messages.c.tool_call_uids).where(
                repo.where(self.scope, segment_ids), messages.c.role == 'assistant', messages.c.tool_calls.is_not(None),
                messages.c.id < before_id).order_by(messages.c.id.desc()).limit(limit))]

    def transcript_handoff_rows(self, shown_ids, segment_ids):
        if not shown_ids:
            return {}
        with self._read() as conn:
            shown = conn.execute(select(messages.c.id, messages.c.message_uid,
                and_(messages.c.session_id.in_(segment_ids), _holder(messages)).label('holds')).where(
                    repo.where(self.scope), messages.c.id.in_(shown_ids))).mappings().all()
            uids = {row['message_uid'] for row in shown if row['message_uid']}
            copies = repo.select_rows(conn, self.scope, segment_ids, messages.c.message_uid.in_(uids),
                messages.c.id < max(shown_ids), _holder(messages)) if uids else []
            holders = {row['id']: row for row in repo.select_rows(conn, self.scope, segment_ids,
                messages.c.id.in_([row['id'] for row in shown if row['holds']]))}
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
        contents = [content_to_bytes(codec._encode_content(content)) for uid, content in handoffs
                    if not uid and isinstance(content, (str, list, dict))]
        if not uids and not contents:
            return []
        shown = messages.alias('handoff_shown')
        held = select(1).where(shown.c.store_id == messages.c.store_id, shown.c.session_id == messages.c.session_id,
            or_(shown.c.id == messages.c.id, and_(messages.c.message_uid.is_not(None), messages.c.message_uid != '',
                shown.c.message_uid == messages.c.message_uid, shown.c.id > messages.c.id)),
            shown.c.id.in_(display_ids(None, self.scope, segment, latest=True, after=before))).correlate(messages).exists()
        match = or_(messages.c.message_uid.in_(uids), and_(or_(messages.c.message_uid.is_(None),
            messages.c.message_uid == ''), messages.c.content.in_(contents)))
        with self._read() as conn:
            rows = repo.select_rows(conn, self.scope, [segment], match, _holder(messages), held)
        return [_handoff(row) for row in rows]


def _holder(table):
    # BYTEA preserves embedded NULs; converting a body to PostgreSQL TEXT would reject those bodies.
    body = func.encode(table.c.content, 'escape')
    return and_(table.c.role.in_(['user', 'assistant']), or_(table.c._compressed_summary == 1,
        body.contains('[CONTEXT COMPACTION', autoescape=True), body.contains('[CONTEXT SUMMARY]', autoescape=True)))


def _handoff(row):
    return codec._row_to_message_dict(row, warn_context='session.transcript', summary_flag=True)


def _page(conn, scope, segment, count, latest, position):
    ids = display_ids(conn, scope, segment, limit=count, latest=latest, after=position)
    return [decoded_row(row) for row in conn.execute(select(messages).where(repo.where(scope, [segment]),
        messages.c.id.in_(ids)).order_by(messages.c.display_order)).mappings()]


def _cursor_slot(conn, scope, segment, durable):
    row = conn.execute(select(messages.c.display_identity, messages.c.display_order, messages.c.active,
        messages.c.compacted, messages.c.message_uid).where(repo.where(scope, [segment]), messages.c.id == durable)).mappings().one_or_none()
    if row is None:
        return None
    if row['display_identity'] is not None:
        copy = conn.scalar(select(messages.c.display_order).where(repo.where(scope, [segment]),
            messages.c.display_identity == row['display_identity'], repo.visible(), messages.c.display_order.is_not(None))
            .order_by(messages.c.active.desc(), messages.c.id.desc()).limit(1))
        if copy is not None:
            return copy
    if row['message_uid']:
        carrier = conn.scalar(select(messages.c.display_order).where(repo.where(scope, [segment]),
            messages.c.message_uid == row['message_uid'], messages.c.active == 1, messages.c._compressed_summary == 1,
            messages.c.display_order.is_not(None)).order_by(messages.c.id.desc()).limit(1))
        if carrier is not None:
            return carrier
    return row['display_order'] if row['active'] == 1 or row['compacted'] == 1 else None


def _durable_firsts(conn, scope, segment, rows):
    identities = {row['display_identity'] for row in rows if row['display_identity'] is not None}
    stamps = {row['timestamp'] for row in rows if row['timestamp'] is not None}
    by_identity = dict(conn.execute(select(messages.c.display_identity, func.min(messages.c.id)).where(
        repo.where(scope, [segment]), messages.c.active == 0, messages.c.compacted == 0, messages.c.timestamp.in_(stamps),
        messages.c.display_identity.in_(identities)).group_by(messages.c.display_identity)).all()) if identities and stamps else {}
    carriers = [row for row in rows if row['_compressed_summary'] and row['message_uid'] and row['timestamp'] is not None]
    by_uid = dict(conn.execute(select(messages.c.message_uid, func.min(messages.c.id)).where(repo.where(scope, [segment]),
        messages.c.active == 0, messages.c.timestamp.in_({row['timestamp'] for row in carriers}),
        messages.c.message_uid.in_({row['message_uid'] for row in carriers})).group_by(messages.c.message_uid)).all()) if carriers else {}
    return {row['id']: min(row['display_order'], by_identity.get(row['display_identity'], row['id']),
        by_uid.get(row['message_uid'], row['id']) if row['_compressed_summary'] else row['id']) for row in rows}
