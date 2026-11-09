"""Native PG search with exact-first recall and stable, bounded result pages."""

from hermes_db.backends.postgresql.search import statement
from hermes_db.repositories import search_context
from hermes_db.search_query import parse_query
from hermes_state_search import SessionSearchMixin


class SessionSearch:
    search_sessions_by_id = SessionSearchMixin.search_sessions_by_id

    def search_messages(self, query, source_filter=None, exclude_sources=None, role_filter=None,
                        limit=20, offset=0, sort=None, include_inactive=False, fields=None, after_ts=None, before_ts=None):
        result_fields = SessionSearchMixin._search_message_fields(fields)
        plan = parse_query(query)
        if not plan.groups or limit <= 0:
            return []
        options = dict(source_filter=source_filter, exclude_sources=exclude_sources, role_filter=role_filter,
            limit=limit, offset=offset, sort=sort, include_inactive=include_inactive, after_ts=after_ts, before_ts=before_ts)
        with self._read() as conn:
            matches = _find(conn, self.scope, plan, options)
            if result_fields is None or "context" in result_fields:
                search_context.attach(conn, self.scope, matches)
        if result_fields is not None:
            return [{field: row[field] for field in result_fields} for row in matches]
        return matches


def _find(conn, scope, plan, options):
    route = "substring" if plan.cjk else "fts"
    matches = [dict(row) for row in conn.execute(statement(scope, plan, route=route, **options)).mappings()]
    if not matches and not plan.cjk and all(len(term[0]) >= 3 for term in plan.terms):
        matches = [dict(row) for row in conn.execute(statement(scope, plan, route="substring", **options)).mappings()]
    if not matches and plan.relaxed and "tool" not in (options.get("role_filter") or ()):
        relaxed = parse_query(plan.relaxed)
        matches = [dict(row) for row in conn.execute(statement(scope, relaxed, **options)).mappings()]
    return matches
