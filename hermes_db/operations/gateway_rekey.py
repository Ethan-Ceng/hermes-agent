"""Exact profile identity rename within one stable store, never a store_id rename."""

import json

from sqlalchemy import and_, literal, func, select

from hermes_db.repositories import sessions
from hermes_db.repositories.gateway import marker
from hermes_db.tables.conversations import sessions as session_table
from hermes_db.tables.gateway import delivery_obligations, gateway_heartbeats, gateway_routing
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings, telegram_dm_topic_mode as modes


def rekey(conn, scope, old_name, new_name):
    old, new = (old_name or "").strip(), (new_name or "").strip()
    if not old or not new or old == new:
        return {}
    sessions.lock_store(conn, scope, exclusive=True)
    old_ns, new_ns = f"agent:{old}:", f"agent:{new}:"
    _assert_no_collision(conn, scope, old, new, old_ns, new_ns)
    counts = {}
    for table, column, label in ((session_table, "profile_name", "sessions_profile_name"),
        (gateway_heartbeats, "profile", "gateway_heartbeats_profile"),
        (delivery_obligations, "adapter_profile", "delivery_obligations_adapter_profile"),
        (modes, "profile_name", "telegram_dm_topic_mode_profile_name"),
        (bindings, "profile_name", "telegram_dm_topic_bindings_profile_name")):
        counts[label] = conn.execute(table.update().where(table.c.store_id == scope.require_store_id(), table.c[column] == old)
            .values(**{column: new})).rowcount
    for table, label in ((session_table, "sessions_session_key"), (delivery_obligations, "delivery_obligations_session_key"),
                         (bindings, "telegram_dm_topic_bindings_session_key")):
        counts[label] = _namespace_column(conn, scope, table, old_ns, new_ns)
    counts["sessions_origin_json"] = _session_origins(conn, scope, old, new)
    counts["gateway_routing"] = _routes(conn, scope, old, new, old_ns, new_ns)
    return counts


def _assert_no_collision(conn, scope, old, new, old_ns, new_ns):
    prior, target = gateway_routing.alias("prior"), gateway_routing.alias("target")
    collision = select(prior.c.scope, target.c.session_key).select_from(prior.join(target, and_(
        target.c.store_id == prior.c.store_id, target.c.scope == prior.c.scope,
        target.c.session_key == literal(new_ns) + func.substr(prior.c.session_key, len(old_ns) + 1)))).where(
        prior.c.store_id == scope.require_store_id(), prior.c.session_key.startswith(old_ns, autoescape=True)).limit(1)
    row = conn.execute(collision).first()
    if row:
        raise ValueError(f"profile routing collision in scope {row[0]!r}: {row[1]!r}")
    for table, columns in ((modes, ("chat_id",)), (bindings, ("chat_id", "thread_id"))):
        prior, target = table.alias("prior"), table.alias("target")
        equal = [target.c.store_id == prior.c.store_id, target.c.profile_name == new,
                 *(target.c[name] == prior.c[name] for name in columns)]
        found = conn.scalar(select(literal(1)).select_from(prior.join(target, and_(*equal))).where(
            prior.c.store_id == scope.require_store_id(), prior.c.profile_name == old).limit(1))
        if found:
            raise ValueError(f"profile identity collision in {table.name}")


def _namespace_column(conn, scope, table, old_ns, new_ns):
    return conn.execute(table.update().where(table.c.store_id == scope.require_store_id(),
        table.c.session_key.startswith(old_ns, autoescape=True))
        .values(session_key=literal(new_ns) + func.substr(table.c.session_key, len(old_ns) + 1))).rowcount


def _session_origins(conn, scope, old, new):
    count = 0
    rows = conn.execute(select(session_table.c.id, session_table.c.origin_json).where(
        session_table.c.store_id == scope.require_store_id(), session_table.c.origin_json.is_not(None))).all()
    for session_id, raw in rows:
        value = marker(raw)
        if value is not None and value.get("profile") == old:
            value["profile"] = new
            sessions.update_session(conn, scope, session_id, {"origin_json": json.dumps(value, ensure_ascii=False)})
            count += 1
    return count


def _routes(conn, scope, old, new, old_ns, new_ns):
    rows = conn.execute(select(gateway_routing).where(gateway_routing.c.store_id == scope.require_store_id(),
        gateway_routing.c.session_key.startswith(old_ns, autoescape=True))).mappings().all()
    for row in rows:
        value = marker(row["entry_json"])
        raw = row["entry_json"]
        if value is not None:
            if isinstance(value.get("session_key"), str) and value["session_key"].startswith(old_ns):
                value["session_key"] = new_ns + value["session_key"][len(old_ns):]
            if isinstance(value.get("origin"), dict) and value["origin"].get("profile") == old:
                value["origin"]["profile"] = new
            raw = json.dumps(value, ensure_ascii=False)
        conn.execute(gateway_routing.update().where(gateway_routing.c.store_id == scope.require_store_id(),
            gateway_routing.c.scope == row["scope"], gateway_routing.c.session_key == row["session_key"])
            .values(session_key=new_ns + row["session_key"][len(old_ns):], entry_json=raw))
    return len(rows)
