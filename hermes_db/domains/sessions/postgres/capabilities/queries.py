"""Listing/counting methods share scoped SQL filter construction."""

from sqlalchemy import func, select, text

from hermes_db.domains.sessions.postgres.queries import sessions as repo, session_queries as queries
from hermes_db.tables.conversations import messages, sessions


class SessionQueries:
    def get_session_rich_row(self, session_id, compact_rows=False):
        self.flush_for_read()
        with self._read() as conn:
            rows = queries.hydrate(conn, self.scope, [session_id], compact=compact_rows)
            return rows[0] if rows else None

    def get_session_list_row(self, session_id):
        fields = ("id", "source", "title", "started_at", "ended_at", "message_count", "model", "hidden", "archived")
        with self._read() as conn:
            row = conn.execute(select(*(sessions.c[name] for name in fields))
                .where(repo.where_session(self.scope, session_id))).mappings().one_or_none()
            return repo.business_row(row) if row else None

    def resolve_session_id(self, session_id_or_prefix):
        with self._read() as conn:
            exact = conn.scalar(select(sessions.c.id).where(repo.where_session(self.scope, session_id_or_prefix)))
            if exact:
                return exact
            rows = list(conn.execute(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.id.startswith(session_id_or_prefix, autoescape=True)).limit(2)).scalars())
            return rows[0] if len(rows) == 1 else None

    def find_session_by_origin(self, *, platform, chat_id, thread_id=None, user_id=None):
        if not platform or chat_id in (None, ""):
            return None
        with self._read() as conn:
            statement = select(sessions.c.id, sessions.c.user_id).where(sessions.c.store_id == self.scope.require_store_id(),
                func.lower(sessions.c.source) == platform.lower(), sessions.c.session_key.is_not(None),
                sessions.c.chat_id == str(chat_id), sessions.c.ended_at.is_(None))
            if thread_id is not None:
                statement = statement.where(func.coalesce(sessions.c.thread_id, "") == str(thread_id))
            rows = list(conn.execute(statement.order_by(sessions.c.started_at.desc())).mappings())
        if not rows:
            return None
        if user_id:
            exact = [row for row in rows if str(row["user_id"] or "") == str(user_id)]
            if exact:
                return exact[0]["id"]
            if len(rows) > 1:
                return None
        elif len({str(row["user_id"] or "").strip() for row in rows if row["user_id"]}) > 1:
            return None
        return rows[0]["id"]

    def list_sessions_rich(self, source=None, sources=None, exclude_sources=None, cwd_prefix=None, limit=20, offset=0,
                           include_children=False, min_message_count=0, project_compression_tips=True, order_by_last_active=False,
                           include_archived=False, archived_only=False, id_query=None, search_query=None, compact_rows=False,
                           include_pinned=False, session_key=None, include_hidden=False, include_subagents=False, local_created_sources=None,
                           workspace_key=None):
        arguments = dict(source=source, sources=sources, session_key=session_key, exclude_sources=exclude_sources,
            cwd_prefix=cwd_prefix, workspace_key=workspace_key, min_message_count=min_message_count, include_archived=include_archived,
            archived_only=archived_only, exclude_children=not include_children, include_subagents=include_subagents,
            local_created_sources=local_created_sources, include_hidden=include_hidden)
        with self._read() as conn:
            clauses = queries.filters(conn, self.scope, **arguments)
            if order_by_last_active:
                clauses += queries.search_filters(conn, id_query, search_query)
            order = queries.lineage_activity(conn).desc() if order_by_last_active else sessions.c.started_at.desc()
            statement = select(sessions.c.id).where(*clauses).order_by(order, sessions.c.started_at.desc(), sessions.c.id.desc())
            ids = list(conn.execute(statement.limit(None if limit < 0 else limit).offset(offset)).scalars())
            if include_pinned:
                arguments.update(include_archived=True, archived_only=False)
                pinned = select(sessions.c.id).where(*queries.filters(conn, self.scope, **arguments), sessions.c.pinned == 1)
                ids.extend(session_id for session_id in conn.execute(pinned.order_by(sessions.c.started_at.desc())).scalars() if session_id not in ids)
            rows = queries.hydrate(conn, self.scope, ids, compact=compact_rows)
            if project_compression_tips and not include_children:
                rows = queries.project_tips(conn, self.scope, rows, compact=compact_rows)
            return rows

    def session_count(self, source=None, sources=None, cwd_prefix=None, min_message_count=0, include_archived=False,
                      archived_only=False, exclude_children=False, exclude_sources=None, include_subagents=False, local_created_sources=None):
        arguments = {key: value for key, value in locals().items() if key != "self"}
        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(sessions).where(*queries.filters(conn, self.scope, **arguments)))

    def session_count_ge(self, n=1):
        if n <= 0:
            return True
        with self._read() as conn:
            return len(list(conn.execute(select(sessions.c.id).where(sessions.c.store_id == self.scope.require_store_id()).limit(n)).scalars())) >= n

    def session_count_by_source(self, *, include_archived=False, archived_only=False, exclude_children=False):
        with self._read() as conn:
            name = func.coalesce(func.nullif(sessions.c.source, ""), "cli")
            rows = conn.execute(select(name, func.count()).where(*queries.filters(conn, self.scope,
                include_archived=include_archived, archived_only=archived_only, exclude_children=exclude_children))
                .group_by(name).order_by(func.count().desc()))
            return {source: count for source, count in rows}

    def search_sessions(self, source=None, limit=20, offset=0, workspace_key=None, local_created_sources=None, skip_launch_stubs=False):
        with self._read() as conn:
            labels = [source] if isinstance(source, str) else source
            clauses = queries.filters(conn, self.scope, sources=labels, include_archived=True, local_created_sources=local_created_sources)
            if workspace_key:
                clauses.append((sessions.c.git_repo_root == workspace_key) | (
                    func.coalesce(sessions.c.git_repo_root, "") == "") & ((sessions.c.cwd == workspace_key)
                    | sessions.c.cwd.startswith(workspace_key.rstrip("/\\") + "/", autoescape=True)
                    | sessions.c.cwd.startswith(workspace_key.rstrip("/\\") + "\\", autoescape=True)))
            if skip_launch_stubs:
                clauses.append(queries.launch_stub_filter(self.scope))
            ids = list(conn.execute(select(sessions.c.id).where(*clauses)
                .order_by(queries.last_activity(conn).desc(), sessions.c.started_at.desc(), sessions.c.id.desc())
                .limit(None if limit < 0 else limit).offset(offset)).scalars())
            return queries.hydrate(conn, self.scope, ids)

    def list_recent_sessions_bounded(self, *, limit=20, exclude_sources=None, timeout_seconds=3.0, candidate_limit=None, lineage_limit=None):
        limit = max(1, int(limit))
        candidates = max(limit, min(int(candidate_limit or max(128, limit * 8)), 2048))
        ceiling = max(candidates, min(int(lineage_limit or min(8192, candidates * 8)), 8192))
        with self._read() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                             {"timeout": str(max(1, int(timeout_seconds * 1000)))})
            roots = queries.bounded_roots(conn, self.scope, exclude_sources, candidates, ceiling)
            clauses = queries.filters(conn, self.scope, exclude_sources=exclude_sources, exclude_children=True, include_hidden=False)
            clauses.append(sessions.c.id.in_(roots))
            ids = list(conn.execute(select(sessions.c.id).where(*clauses)
                .order_by(queries.lineage_activity(conn).desc(), sessions.c.id.desc()).limit(limit)).scalars())
            rows = queries.project_tips(conn, self.scope, queries.hydrate(conn, self.scope, ids))
            for row in rows:
                row["unread"] = self.session_unread(row)
            return rows

    def session_lifecycle_statuses(self, session_ids):
        from hermes_state_sessions import classify_session_status
        ids = [value for value in session_ids or [] if value]
        result = {value: "empty" for value in ids}
        if not ids:
            return result
        with self._read() as conn:
            latest = select(messages.c.session_id, func.max(messages.c.id).label("latest_id")).where(
                messages.c.store_id == self.scope.require_store_id(), messages.c.session_id.in_(ids)).group_by(messages.c.session_id).subquery()
            rows = conn.execute(select(messages.c.session_id, messages.c.role, messages.c.tool_calls, messages.c.finish_reason)
                .join(latest, (messages.c.session_id == latest.c.session_id) & (messages.c.id == latest.c.latest_id))
                .where(messages.c.store_id == self.scope.require_store_id())).mappings()
            for row in rows:
                result[row["session_id"]] = classify_session_status(row["role"], row["tool_calls"] is not None, row["finish_reason"])
        return result

    def count_empty_sessions(self):
        from sqlalchemy import exists

        with self._read() as conn:
            return conn.scalar(select(func.count()).select_from(sessions).where(
                sessions.c.store_id == self.scope.require_store_id(), sessions.c.message_count == 0,
                sessions.c.ended_at.is_not(None), sessions.c.archived == 0,
                ~exists(select(1).where(messages.c.store_id == sessions.c.store_id, messages.c.session_id == sessions.c.id))))
