"""Dashboard usage aggregates with local calendar days and exact scoped joins."""

from datetime import datetime

from sqlalchemy import and_, cast, Float, func, select

from hermes_db.tables.conversations import session_model_usage as u, sessions as s

COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")


def _sum(table, name, alias=None, *, zero=False):
    value = func.sum(table.c[name])
    return (func.coalesce(value, 0) if zero else value).label(alias or name)


def _costs(table):
    return [_sum(table, "estimated_cost_usd", "estimated_cost", zero=True),
        _sum(table, "actual_cost_usd", "actual_cost", zero=True)]


def _totals(kind):
    names = dict(input_tokens="total_input", output_tokens="total_output", cache_read_tokens="total_cache_read",
        reasoning_tokens="total_reasoning", estimated_cost_usd="total_estimated_cost", actual_cost_usd="total_actual_cost",
        api_call_count="total_api_calls")
    statement = select(*(_sum(s, name, alias, zero=name.endswith("cost_usd")) for name, alias in names.items()),
        func.count().label("total_sessions"))
    return statement.where(s.c.model.is_not(None), s.c.model != "") if kind == "model_totals" else statement


def _sessions(kind):
    if kind in ("totals", "model_totals"):
        return _totals(kind)
    if kind == "tool_calls":
        return select(s.c.model, s.c.billing_provider, _sum(s, "tool_call_count", "tool_calls", zero=True)).where(
            s.c.model.is_not(None), s.c.model != "").group_by(s.c.model, s.c.billing_provider)
    if kind not in ("by_model", "models_fallback"):
        raise ValueError("Unknown dashboard analytics query")
    columns = [s.c.model, _sum(s, "input_tokens"), _sum(s, "output_tokens"),
        _sum(s, "estimated_cost_usd", "estimated_cost", zero=True), func.count().label("sessions"), _sum(s, "api_call_count", "api_calls", zero=True)]
    groups = [s.c.model]
    if kind == "models_fallback":
        columns.extend([s.c.billing_provider, _sum(s, "cache_read_tokens"), _sum(s, "reasoning_tokens"),
            _sum(s, "actual_cost_usd", "actual_cost", zero=True), _sum(s, "tool_call_count", "tool_calls"),
            func.max(s.c.started_at).label("last_used_at"), cast(func.avg(s.c.input_tokens + s.c.output_tokens), Float).label("avg_tokens_per_session")])
        groups.append(s.c.billing_provider)
    statement = select(*columns).where(s.c.model.is_not(None)).group_by(*groups).order_by((func.sum(s.c.input_tokens) + func.sum(s.c.output_tokens)).desc())
    return statement.where(s.c.model != "") if kind == "models_fallback" else statement


def _usage(auxiliary):
    columns = [u.c.model, u.c.billing_provider, *(_sum(u, name) for name in COUNTERS), *_costs(u),
        func.count(func.distinct(u.c.session_id)).label("sessions"), _sum(u, "api_call_count", "api_calls", zero=True),
        func.max(u.c.last_seen).label("last_used_at")]
    groups = [u.c.model, u.c.billing_provider]
    if auxiliary:
        columns.append(u.c.task)
        groups.append(u.c.task)
    else:
        columns.append(cast(func.avg(u.c.input_tokens + u.c.output_tokens), Float).label("avg_tokens_per_session"))
    statement = select(*columns).select_from(u.join(s, and_(s.c.store_id == u.c.store_id, s.c.id == u.c.session_id)))
    condition = u.c.task != "" if auxiliary else and_(u.c.task == "", u.c.model.is_not(None), u.c.model != "")
    return statement.where(condition).group_by(*groups).order_by((func.sum(u.c.input_tokens) + func.sum(u.c.output_tokens)).desc())


def _daily(conn, scope, cutoff):
    # The host's local calendar can cross DST boundaries inside one window.
    # Project only counters; converting each timestamp here matches Insights.
    columns = ("started_at", *COUNTERS, "estimated_cost_usd", "actual_cost_usd", "api_call_count")
    rows = conn.execute(select(*(s.c[name] for name in columns)).where(s.c.store_id == scope.require_store_id(), s.c.started_at > cutoff))
    days = {}
    for row in rows.mappings():
        day = datetime.fromtimestamp(row["started_at"]).date().isoformat()
        target = days.setdefault(day, dict(day=day, **dict.fromkeys((*COUNTERS, "estimated_cost", "actual_cost", "sessions", "api_calls"), 0)))
        target["sessions"] += 1
        for name, alias in [(key, key) for key in COUNTERS] + [("estimated_cost_usd", "estimated_cost"), ("actual_cost_usd", "actual_cost"), ("api_call_count", "api_calls")]:
            target[alias] += row[name] or 0
    return [days[day] for day in sorted(days)]


def rows(conn, scope, kind, cutoff):
    if kind == "daily":
        return _daily(conn, scope, cutoff)
    statement = _usage(kind == "auxiliary") if kind in ("auxiliary", "models_main") else _sessions(kind)
    if kind == "by_model":
        statement = statement.order_by(None).order_by((func.sum(s.c.input_tokens) + func.sum(s.c.output_tokens)).desc())
    return [dict(row) for row in conn.execute(statement.where(s.c.store_id == scope.require_store_id(), s.c.started_at > cutoff)).mappings()]
