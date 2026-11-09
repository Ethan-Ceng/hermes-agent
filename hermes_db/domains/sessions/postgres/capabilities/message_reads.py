"""Raw transcript and cache-stable conversation projections."""

from sqlalchemy import Text, cast, func, select

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.queries import messages as repo, sessions as session_repo
from hermes_db.tables.conversations import messages, sessions


class SessionMessageReads:
    def transcript_cursor_state(self, session_id, through_id, lineage_ids=None):
        from sqlalchemy import or_
        with self._read() as conn:
            ids = list(lineage_ids) if lineage_ids else _transcript_lineage_ids(conn, self.scope, session_id)
            live = conn.scalar(select(func.count()).select_from(messages).where(
                repo.where(self.scope, ids), messages.c.active == 1,
                or_(messages.c.session_id != session_id, messages.c.id <= int(through_id))))
            inactive = conn.scalar(select(func.count()).select_from(messages).where(
                repo.where(self.scope, ids), messages.c.active == 0))
            edits = conn.scalar(select(func.coalesce(func.sum(sessions.c.transcript_edit_revision), 0)).where(
                sessions.c.store_id == self.scope.require_store_id(), sessions.c.id.in_(ids)))
            return int(live), int(inactive), int(edits)

    def transcript_lineage_ids(self, session_id):
        with self._read() as conn:
            return _transcript_lineage_ids(conn, self.scope, session_id)

    def get_messages(self, session_id, include_inactive=False, include_compacted=False, limit=None, offset=0,
                     latest=False, after_id=None, include_ancestors=False):
        if after_id is not None and (latest or offset or include_compacted or include_ancestors):
            raise ValueError("after_id is incompatible with latest/offset/compacted/ancestor paging")
        with self._read() as conn:
            ids = repo.resume_lineage(conn, self.scope, session_id) if include_ancestors else [session_id]
            if len(ids) > 1 or include_compacted:
                # The full lineage is needed to suppress removed logical copies.
                # Single-segment display reads use the indexed page below.
                rows = _display_page(conn, self.scope, session_id, limit, offset, latest) if len(ids) == 1 and not include_inactive else None
                if rows is None:
                    rows = repo.display_set(conn, self.scope, ids) if include_compacted and not include_inactive else repo.select_rows(
                        conn, self.scope, ids, *_active_filter(include_inactive, include_compacted))
                    rows = codec._dedupe_display_generations(rows, drop_removed=include_compacted and not include_inactive)
                    rows = _page(rows, limit, offset, latest)
            else:
                conditions = _active_filter(include_inactive, include_compacted)
                if after_id is not None:
                    conditions.append(messages.c.id > after_id)
                rows = repo.select_rows(conn, self.scope, ids, *conditions, limit=limit, offset=offset, latest=latest)
        return [codec._row_to_message_dict(row, warn_context="get_messages", summary_flag=True) for row in rows]

    def get_messages_as_conversation(self, session_id, include_ancestors=False, include_inactive=False,
                                     repair_alternation=False, include_row_ids=False, include_compacted=False):
        with self._read() as conn:
            ids = repo.resume_lineage(conn, self.scope, session_id) if include_ancestors else [session_id]
            conditions = [] if include_compacted and not include_inactive else _active_filter(include_inactive, include_compacted)
            rows = repo.display_set(conn, self.scope, ids) if include_compacted and not include_inactive else repo.select_rows(
                conn, self.scope, ids, *conditions)
        if include_compacted:
            rows = codec._dedupe_display_generations(rows, drop_removed=not include_inactive)
        return codec._rows_to_conversation(rows, session_id=session_id, include_ancestors=include_ancestors,
            repair_alternation=repair_alternation, include_row_ids=include_row_ids, include_summary_markers=repair_alternation)

    def get_resume_conversations(self, session_id):
        with self._read() as conn:
            rows = repo.display_set(conn, self.scope, repo.resume_lineage(conn, self.scope, session_id))
        model = codec._rows_to_conversation(
            [row for row in rows if row["session_id"] == session_id and row["active"] and row["role"] != "session_meta"],
            session_id=session_id, include_ancestors=False, repair_alternation=True, include_row_ids=True, include_summary_markers=True)
        display = codec._rows_to_conversation(codec._dedupe_display_generations(rows, drop_removed=True),
            session_id=session_id, include_ancestors=True, repair_alternation=False, include_row_ids=True)
        return model, display

    def get_active_message_ids(self, session_id):
        with self._read() as conn:
            return repo.active_ids(conn, self.scope, session_id)

    def get_active_message_watermark(self, session_id):
        # IDs are allocated after the same root lock every appender holds.
        # A snapshot cannot observe a later committed ID past an earlier writer.
        with self._write() as conn:
            session_repo.lock_session(conn, self.scope, session_id)
            return conn.scalar(select(func.coalesce(func.max(messages.c.id), 0)).where(
                repo.where(self.scope, [session_id]), messages.c.active == 1))

    def conversation_revision(self, session_id, include_ancestors=False):
        with self._read() as conn:
            ids = repo.resume_lineage(conn, self.scope, session_id) if include_ancestors else [session_id]
            count, highest = conn.execute(select(func.count(), func.coalesce(func.max(messages.c.id), 0))
                .where(repo.where(self.scope, ids), messages.c.active == 1)).one()
            revision = conn.scalar(select(func.coalesce(func.sum(sessions.c.transcript_revision), 0)).where(
                sessions.c.store_id == self.scope.require_store_id(), sessions.c.id.in_(ids)))
        return tuple(ids), count, highest, revision

    def message_count(self, session_id=None):
        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(messages).where(
                repo.where(self.scope, [session_id] if session_id else None)))

    def has_archived_messages(self, session_id):
        with self._read() as conn:
            return conn.scalar(select(messages.c.id).where(repo.where(self.scope, [session_id]), messages.c.active == 0).limit(1)) is not None

    def get_resume_message_count(self, session_id, *, tip_only=False):
        with self._read() as conn:
            return _resume_count(conn, self.scope, session_id, tip_only)

    def assert_resume_safe(self, session_id, max_messages=None, *, tip_only=False):
        from hermes_state import SessionResumeTooLargeError, resolved_max_resume_messages
        if max_messages is None:
            with self._profile.activate():
                max_messages = resolved_max_resume_messages()
        if max_messages < 0:
            raise ValueError("max_messages must be non-negative")
        if max_messages == 0:
            return 0
        with self._read() as conn:
            count = _resume_count(conn, self.scope, session_id, tip_only, max_messages + 1)
        if count > max_messages:
            raise SessionResumeTooLargeError(count, max_messages, scope="in its tip segment" if tip_only else "across its lineage")
        return count

    def get_ancestor_display_prefix(self, session_id):
        with self._read() as conn:
            rows = repo.display_set(conn, self.scope, repo.resume_lineage(conn, self.scope, session_id))
        rows = codec._dedupe_display_generations(rows, drop_removed=True)
        ancestor_ids = {row["id"] for row in rows if row["session_id"] != session_id}
        conversation = codec._rows_to_conversation(rows, session_id=session_id, include_ancestors=True,
                                                  repair_alternation=False, include_row_ids=True)
        return [{key: value for key, value in msg.items() if key != "_row_id"}
                for msg in conversation if msg.get("_row_id") in ancestor_ids]

    def get_conversation_root(self, session_id):
        with self._read() as conn:
            current, seen = session_id, set()
            while current not in seen:
                seen.add(current)
                row = session_repo.raw_session(conn, self.scope, current)
                if not row or not row["parent_session_id"]:
                    return current
                parent = session_repo.raw_session(conn, self.scope, row["parent_session_id"])
                if not parent:
                    return current
                current = parent["id"]
        raise ValueError("Conversation lineage contains a cycle")

    def is_explicit_fork_child(self, session_id):
        row = self.get_session(session_id)
        from hermes_state_messages import SessionMessagesMixin
        return bool(row and SessionMessagesMixin._is_explicit_fork_child_row(self, row))


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
    from hermes_db.backends.postgresql.expressions.projections import display_value, query_token
    from agent.context_compressor import MODEL_ONLY_DISPLAY_METADATA_KEY

    original = messages.alias("original")
    model_only = tuple(query_token(value) for value in (True, 1, 'true', '1'))
    copied_tool = select(1).where(original.c.store_id == messages.c.store_id, original.c.session_id == messages.c.session_id,
        original.c.timestamp == messages.c.timestamp, original.c.message_uid == messages.c.message_uid,
        original.c.role == "tool", original.c.active == 0, original.c.compacted == 1,
        original.c.display_order < messages.c.display_order,
        func.coalesce(cast(display_value(original.c.display_metadata, MODEL_ONLY_DISPLAY_METADATA_KEY), Text), "false").not_in(model_only)).exists()
    eligible = [repo.where(scope, [session_id]), repo.visible(),
        func.coalesce(cast(display_value(messages.c.display_metadata, MODEL_ONLY_DISPLAY_METADATA_KEY), Text), "false").not_in(model_only),
        ~((messages.c.role == "tool") & messages.c.message_uid.is_not(None) & copied_tool)]
    if after is not None:
        eligible.append(messages.c.display_order < after if latest else messages.c.display_order > after)
    ranked = select(messages.c.id, messages.c.display_order,
        func.row_number().over(partition_by=messages.c.display_order, order_by=(messages.c.active.desc(), messages.c.id.desc()))
        .label("rank")).where(*eligible).subquery()
    page = select(ranked.c.id).where(ranked.c.rank == 1).order_by(ranked.c.display_order.desc() if latest else ranked.c.display_order)
    if limit is not None:
        page = page.limit(limit)
    if offset:
        page = page.offset(offset)
    return page


def _display_page(conn, scope, session_id, limit, offset, latest):
    page = display_ids(conn, scope, session_id, limit, offset, latest)
    from hermes_db.domains.sessions.postgres.support.message_codec import decoded_row
    return [decoded_row(row) for row in conn.execute(select(messages).where(repo.where(scope, [session_id]),
        messages.c.id.in_(page)).order_by(messages.c.display_order)).mappings()]


def _transcript_lineage_ids(conn, scope, session_id):
    from hermes_db.core.values import model_config
    row = session_repo.get_session(conn, scope, session_id)
    if row is None or not model_config(row.get("model_config")).get("_delegate_from"):
        return [session_id]
    return repo.resume_lineage(conn, scope, session_id)
