"""Named Insights reads over scoped Core expressions; no SQL string translation."""

from sqlalchemy import and_, case, func, or_, select

from hermes_db.tables.conversations import messages as m, session_model_usage as u, sessions as s

SESSION_COLUMNS = ("id", "source", "model", "started_at", "ended_at", "message_count", "tool_call_count",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "billing_provider", "billing_base_url",
    "billing_mode", "estimated_cost_usd", "actual_cost_usd", "cost_status", "cost_source", "api_call_count")
USAGE_COLUMNS = ("session_id", "model", "billing_provider", "billing_base_url", "api_call_count", "input_tokens",
    "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "estimated_cost_usd",
    "actual_cost_usd", "cost_status", "cost_source", "billing_mode")


def _filter(scope, cutoff, source):
    conditions = [s.c.store_id == scope.require_store_id(), s.c.started_at >= cutoff]
    if source:
        conditions.append(or_(s.c.source == source, and_(s.c.source == "local", s.c.created_source == source)))
    return conditions


def _messages(conn, kind):
    joined = m.join(s, and_(s.c.store_id == m.c.store_id, s.c.id == m.c.session_id))
    if kind == "_GET_MESSAGE_STATS":
        return select(func.count().label("total_messages"),
            *(func.sum(case((m.c.role == role, 1), else_=0)).label(role + "_messages") for role in ("user", "assistant", "tool"))).select_from(joined)
    if kind == "_GET_TOOL_NAMES":
        return select(m.c.session_id, m.c.tool_name, func.count().label("count")).select_from(joined).where(
            m.c.role == "tool", m.c.tool_name.is_not(None)).group_by(m.c.session_id, m.c.tool_name)
    if kind not in ("_GET_TOOL_CALLS", "_GET_SKILL_CALLS"):
        raise ValueError("Unknown Insights query")
    columns = [m.c.tool_calls, m.c.timestamp] if kind == "_GET_SKILL_CALLS" else [m.c.session_id, m.c.tool_calls]
    statement = select(*columns).select_from(joined).where(m.c.role == "assistant", m.c.tool_calls.is_not(None))
    if kind == "_GET_SKILL_CALLS":
        text = m.c.tool_calls
        statement = statement.where(or_(text.contains("skill_view", autoescape=True), text.contains("skill_manage", autoescape=True)))
    return statement


def rows(conn, scope, kind, cutoff, source):
    if kind == "_GET_SESSIONS":
        statement = select(*(s.c[name] for name in SESSION_COLUMNS)).order_by(s.c.started_at.desc())
    elif kind == "_GET_MODEL_USAGE":
        statement = select(*(u.c[name] for name in USAGE_COLUMNS)).select_from(u.join(s,
            and_(s.c.store_id == u.c.store_id, s.c.id == u.c.session_id)))
    else:
        statement = _messages(conn, kind)
    return [dict(row) for row in conn.execute(statement.where(*_filter(scope, cutoff, source))).mappings()]
