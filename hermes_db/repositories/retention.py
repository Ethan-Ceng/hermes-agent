"""Scoped activity/retention selectors shared by previews and atomic maintenance."""

import time

from sqlalchemy import func, or_, select

from hermes_db.repositories import session_queries, sessions
from hermes_db.tables.conversations import sessions as table
from hermes_db.core.values import explicit_fork


def not_pinned():
    peer = table.alias("pinned_peer")
    return ~select(peer.c.id).where(peer.c.store_id == table.c.store_id,
        peer.c.lineage_root_id == table.c.lineage_root_id, peer.c.pinned != 0).correlate(table).exists()


def _substring(column, value):
    return func.lower(func.coalesce(column, "")).contains(value.lower(), autoescape=True)


def _cwd(value):
    prefix = value.rstrip("/\\") or value
    return or_(table.c.cwd == prefix, table.c.cwd.startswith(prefix + "/", autoescape=True),
        table.c.cwd.startswith(prefix + "\\", autoescape=True))


def _specs(conn):
    activity = session_queries.last_activity(conn)
    tokens = func.coalesce(table.c.input_tokens, 0) + func.coalesce(table.c.output_tokens, 0)
    cost = func.coalesce(table.c.actual_cost_usd, table.c.estimated_cost_usd, 0)
    tools = func.coalesce(table.c.tool_call_count, 0)
    return {
        "last_active_before": (True, lambda value: [activity < value,
            or_(func.coalesce(table.c.end_reason, "") != "startup_orphan_reap", table.c.ended_at < value)]),
        "last_active_after": (True, lambda value: [activity >= value]),
        "started_before": (True, lambda value: [table.c.started_at < value]),
        "started_after": (True, lambda value: [table.c.started_at >= value]),
        "source": (False, lambda value: [table.c.source == value]),
        "title_like": (False, lambda value: [_substring(table.c.title_search, value)]),
        "end_reason": (False, lambda value: [table.c.end_reason == value]),
        "cwd_prefix": (False, lambda value: [_cwd(value)]),
        "min_messages": (True, lambda value: [table.c.message_count >= value]),
        "max_messages": (True, lambda value: [table.c.message_count <= value]),
        "model_like": (False, lambda value: [_substring(table.c.model, value)]),
        "provider": (False, lambda value: [func.lower(func.coalesce(table.c.billing_provider, "")) == value.lower()]),
        "user_id": (False, lambda value: [table.c.user_id == value]),
        "chat_id": (False, lambda value: [table.c.chat_id == value]),
        "chat_type": (False, lambda value: [table.c.chat_type == value]),
        "branch_like": (False, lambda value: [_substring(table.c.git_branch, value)]),
        "min_tokens": (True, lambda value: [tokens >= value]),
        "max_tokens": (True, lambda value: [tokens <= value]),
        "min_cost": (True, lambda value: [cost >= value]),
        "max_cost": (True, lambda value: [cost <= value]),
        "min_tool_calls": (True, lambda value: [tools >= value]),
        "max_tool_calls": (True, lambda value: [tools <= value]),
    }


def conditions(conn, scope, older_than_days, source, filters, *, only_open=False):
    values, specs = {**filters, "source": source}, _specs(conn)
    unknown = set(values) - set(specs) - {"archived", "include_pinned", "lineage_tips_only", "include_open"}
    if unknown:
        raise TypeError(f"Unknown retention filter: {min(unknown)}")
    if older_than_days is not None and values.get("last_active_before") is None and values.get("started_before") is None:
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")
        values["last_active_before"] = time.time() - older_than_days * 86400
    clauses = [table.c.store_id == scope.require_store_id()]
    if only_open:
        clauses.append(table.c.ended_at.is_(None))
    elif not values.get("include_open"):
        clauses.append(table.c.ended_at.is_not(None))
    if values.get("lineage_tips_only"):
        clauses.append(func.coalesce(table.c.end_reason, "") != "compression")
        clauses.append((table.c.title.is_(None)) | (table.c.title != b'Bot Chat'))
    if isinstance(values.get("archived"), bool):
        clauses.append(table.c.archived == int(values["archived"]))
    if not values.get("include_pinned"):
        clauses.append(not_pinned())
    for name, (numeric, build) in specs.items():
        value = values.get(name)
        if (value is not None) if numeric else bool(value):
            clauses.extend(build(value))
    return clauses


def candidates(conn, scope, older_than_days=None, source=None, *, whole_lineages=False, **filters):
    activity = session_queries.last_activity(conn)
    fields = ("id", "source", "title", "model", "started_at", "ended_at", "message_count", "archived", "lineage_root_id")
    statement = select(*(table.c[name] for name in fields), activity.label("last_active")).where(
        *conditions(conn, scope, older_than_days, source, filters)).order_by(activity, table.c.started_at, table.c.id)
    rows = [dict(row) for row in conn.execute(statement).mappings()]
    if whole_lineages:
        protected = _continued_ancestors(conn, scope, rows)
        rows = [row for row in rows if row["id"] not in protected]
    for row in rows:
        row.pop("lineage_root_id")
    return [sessions.business_row(row) for row in rows]


def _continued_ancestors(conn, scope, selected):
    roots = sorted({row["lineage_root_id"] for row in selected})
    rows = {}
    for start in range(0, len(roots), 1000):
        statement = select(table.c.id, table.c.parent_session_id, table.c.end_reason, table.c.model_config).where(
            table.c.store_id == scope.require_store_id(), table.c.lineage_root_id.in_(roots[start:start + 1000]))
        rows.update({row["id"]: dict(row) for row in conn.execute(statement).mappings()})
    picked, protected = {row["id"] for row in selected}, set()
    for child in (row for sid, row in rows.items() if sid not in picked):
        while child and not explicit_fork(child):
            parent = rows.get(child["parent_session_id"])
            if not parent or parent["end_reason"] != "compression" or parent["id"] in protected:
                break
            protected.add(parent["id"])
            child = parent
    return protected
