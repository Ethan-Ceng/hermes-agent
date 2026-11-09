"""PostgreSQL indexed full-text and substring expressions, always scope-filtered."""

import re

from sqlalchemy import and_, case, cast, false, func, literal, literal_column, not_, or_, select
from sqlalchemy.dialects.postgresql import JSON

from hermes_db.domains.sessions.postgres.queries.messages import visible, where
from hermes_db.domains.sessions.postgres.support.search_projection import short_grams
from hermes_db.tables.conversations import message_search_chunks as chunks, messages as m, sessions as s
from hermes_db.domains.sessions.rules import FTS_TRIGRAM_EXCLUDED_SOURCES

SIMPLE = literal_column("'pg_catalog.simple'::regconfig")


def _text_query(value, prefix):
    if not prefix:
        return func.phraseto_tsquery(SIMPLE, value)
    words = re.findall(r"[^\W_]+", value)
    if not words:
        return func.plainto_tsquery(SIMPLE, "")
    escaped = ["'" + word.replace("'", "''").replace("\\", "\\\\") + "'" for word in words]
    escaped[-1] += ":*"
    return func.to_tsquery(SIMPLE, " <-> ".join(escaped))


def _term(term, route, document):
    value, prefix, _ = term
    if route == "fts":
        indexed = select(chunks.c.message_id).where(chunks.c.store_id == m.c.store_id, chunks.c.message_id == m.c.id,
            chunks.c.search_vector.op("@@")(_text_query(value, prefix))).correlate(m).exists()
        words = re.findall(r"[^\W_]+", value)
        if len(words) > 1:
            # Phrase positions may exceed PG's per-lexeme position cap or a chunk
            # boundary. Indexed candidates plus a lexical recheck retain recall.
            phrase = "(^|[^[:alnum:]])" + "[^[:alnum:]]+".join(re.escape(word) for word in words)
            if not prefix:
                phrase += "($|[^[:alnum:]])"
            return or_(indexed, and_(m.c.search_grams.contains(short_grams(value)), document.op("~*")(phrase)))
        return indexed
    pattern = "%" + value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    exact = document.ilike(pattern, escape="\\")
    if route == "substring":
        grams = short_grams(value)
        return and_(m.c.search_grams.contains(grams), exact) if grams else exact
    return exact


def _predicate(plan, route, document):
    groups, positive = [], []
    for group in plan.groups:
        terms = []
        for term in group:
            match = _term(term, route, document)
            terms.append(not_(match) if term[2] else match)
            if not term[2]:
                positive.append(match)
        groups.append(and_(*terms))
    return or_(*groups) if groups else false(), positive


def _filters(scope, options, *, substring=False):
    clauses = [where(scope), s.c.store_id == scope.require_store_id()]
    if not options.get("include_inactive"):
        clauses.append(visible())
    for key, column, exclude in (("source_filter", s.c.source, False), ("exclude_sources", s.c.source, True),
                                  ("role_filter", m.c.role, False)):
        values = options.get(key)
        if values:
            clauses.append(column.not_in(values) if exclude else column.in_(values))
    for key, predicate in (("after_ts", lambda value: s.c.started_at >= int(value)), ("before_ts", lambda value: s.c.started_at < int(value))):
        if options.get(key) is not None:
            clauses.append(predicate(options[key]))
    if substring and not _full_body(options):
        delegated = cast(s.c.model_config, JSON).op("->")("_delegate_from")
        clauses.extend((m.c.role != "tool", s.c.source.not_in(FTS_TRIGRAM_EXCLUDED_SOURCES),
            or_(delegated.is_(None), func.json_typeof(delegated) == "null")))
    return clauses


def _full_body(options):
    return "tool" in (options.get("role_filter") or ()) or any(
        source in FTS_TRIGRAM_EXCLUDED_SOURCES for source in (options.get("source_filter") or ()))


def statement(scope, plan, *, route="fts", **options):
    # Explicit tool/source searches opt into canonical full-body scans, as SQLite does.
    if _full_body(options) and (plan.cjk or "tool" in (options.get("role_filter") or ())):
        route = "full_body"
    document = func.lower(func.coalesce(m.c.search_content, "") + "\n" + func.coalesce(m.c.tool_name, "") + "\n" + func.coalesce(m.c.tool_calls, "")) if route == "full_body" else m.c.search_document
    predicate, positive = _predicate(plan, route, document)
    score = sum((case((match, 1), else_=0) for match in positive), literal(0))
    sort = str(options.get("sort") or "").strip().lower()
    orders = {"newest": (m.c.timestamp.desc(), score.desc()), "oldest": (m.c.timestamp, score.desc())}
    ordering = orders.get(sort, (score.desc(), m.c.timestamp.desc())) if positive else (m.c.timestamp.desc(),)
    needle = plan.terms[0][0].lower() if plan.terms else ""
    snippet = func.substr(document, func.greatest(1, func.strpos(func.lower(document), needle) - 40), 120)
    return select(m.c.id, m.c.session_id, m.c.role, m.c.timestamp, m.c.tool_name, s.c.source, s.c.model,
        s.c.started_at.label("session_started"), snippet.label("snippet")).select_from(
        m.join(s, and_(m.c.store_id == s.c.store_id, m.c.session_id == s.c.id))).where(
        *_filters(scope, options, substring=route == "substring"), predicate).order_by(*ordering, m.c.id).limit(
        max(0, int(options.get("limit", 20)))).offset(max(0, int(options.get("offset", 0))))
