"""Route/task attribution and summary counters on the caller's Connection."""

import time

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.sessions.postgres.queries import sessions as repo
from hermes_db.tables.conversations import session_model_usage as usage

COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "api_call_count")
ROUTE = ("model", "billing_provider", "billing_base_url", "billing_mode")
COSTS = ("estimated_cost_usd", "actual_cost_usd")


def record_route(conn, scope, session_id, values, *, task=""):
    row = repo.raw_session(conn, scope, session_id) if not task else {}
    now = time.time()
    data = {name: values.get(name) or row.get(name) or ("unknown" if name == "model" else "") for name in ROUTE}
    data.update({name: values.get(name) or 0 for name in (*COUNTERS, *COSTS)})
    data.update(store_id=scope.require_store_id(), session_id=session_id, task=task or "",
                cost_status=values.get("cost_status"), cost_source=values.get("cost_source"), first_seen=now, last_seen=now)
    data["usage_order"] = 1 + (conn.scalar(select(func.max(usage.c.usage_order)).where(
        usage.c.store_id == scope.require_store_id(), usage.c.session_id == session_id)) or 0)
    statement = insert(usage).values(**data)
    updates = {name: usage.c[name] + statement.excluded[name] for name in (*COUNTERS, *COSTS)}
    updates.update(last_seen=now)
    updates.update({name: func.coalesce(statement.excluded[name], usage.c[name]) for name in ("cost_status", "cost_source")})
    conn.execute(statement.on_conflict_do_update(index_elements=list(usage.primary_key.columns), set_=updates))


def update_totals(conn, scope, session_id, values):
    row = repo.lock_session(conn, scope, session_id)
    absolute = values.get("absolute", False)
    task = values.get("task", "")
    update = {name: _counter_value(name, row[name], values.get(name, 0), absolute) for name in COUNTERS}
    estimate = values.get("estimated_cost_usd") or 0.0
    update["estimated_cost_usd"] = estimate + (0 if absolute else row["estimated_cost_usd"] or 0.0)
    if values.get("actual_cost_usd") is not None:
        update["actual_cost_usd"] = values["actual_cost_usd"] + (0 if absolute else row["actual_cost_usd"] or 0.0)
    for name in ("cost_status", "cost_source", "pricing_version"):
        if values.get(name) is not None:
            update[name] = values[name]
    has_usage = any(values.get(name) for name in (*COUNTERS, "estimated_cost_usd"))
    has_accounted = has_usage or bool(values.get("actual_cost_usd"))
    first_route = (not task and not row["api_call_count"] and has_accounted
                   and values.get("model") and values.get("billing_provider")
                   and (row["model"] != values.get("model") or row["billing_provider"] != values.get("billing_provider")))
    if has_accounted:
        for name in ROUTE:
            if first_route or row[name] is None:
                update[name] = values.get(name)
    repo.update_session(conn, scope, session_id, update)
    if not absolute and has_usage:
        record_route(conn, scope, session_id, values, task=task)


def _counter_value(name, current, value, absolute):
    if absolute:
        return value
    if name == "api_call_count":
        current = current or 0
    return current + value if current is not None and value is not None else None


def recent_route(conn, scope, session_id):
    row = conn.execute(select(usage.c.model, usage.c.billing_provider, usage.c.billing_base_url, usage.c.billing_mode, usage.c.api_call_count)
        .where(usage.c.store_id == scope.require_store_id(), usage.c.session_id == session_id,
               usage.c.task == "", usage.c.model != "unknown", usage.c.billing_provider != "")
        .order_by(usage.c.last_seen.desc(), usage.c.usage_order.desc()).limit(1)).mappings().one_or_none()
    return dict(row) if row else None
