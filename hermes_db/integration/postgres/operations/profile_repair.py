"""Fenced, current-data Profile labels, parent links, routes and topic repairs."""

import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.sessions.postgres.operations import retirement, retirement_guards as guards
from hermes_db.domains.sessions.postgres.queries import gateway, sessions
from hermes_db.integration.postgres.queries import profile_repair as repo
from hermes_db.tables.gateway import gateway_routing as routes
from hermes_db.tables.gateway import telegram_dm_topic_bindings as bindings, telegram_dm_topic_mode as modes
from hermes_state_profile_repair import session_key_profile


def repair_sessions(conn, scope, ids, *, sever=False, rekey=None):
    wanted = set(ids)
    sessions.lock_store(conn, scope, exclusive=True)
    rows = [row for row in repo.keyed_rows(conn, scope) if row["id"] in wanted]
    guards.lock_targets(conn, scope, [row["id"] for row in rows])
    guards.require_unleased(conn, scope, [row["id"] for row in rows])
    count, detached = 0, []
    for row in rows:
        mine, theirs = session_key_profile(row["session_key"]), session_key_profile(row["parent_session_key"])
        if sever:
            if mine is not None and theirs is not None and mine != theirs:
                count += sessions.update_session(conn, scope, row["id"], {"parent_session_id": None})
                detached.append(row["id"])
        elif rekey is not None:
            if row["session_key"].startswith("agent:main:"):
                from gateway.session_contract import _session_key_namespace
                count += sessions.update_session(conn, scope, row["id"], {
                    "profile_name": rekey, "session_key": _session_key_namespace(rekey) + ":" + row["session_key"][11:]})
        elif mine is not None and row["profile_name"] != mine:
            count += sessions.update_session(conn, scope, row["id"], {"profile_name": mine})
    retirement._rebase_orphans(conn, scope, detached)
    return count


def delete_routes(conn, scope, wanted):
    from hermes_db.domains.runtime.receipts import entry_session_id, route_namespace
    sessions.lock_store(conn, scope, exclusive=True)
    requested, count = set(wanted), 0
    for row in gateway.routing_rows(conn, scope):
        if (row["scope"], row["session_key"]) not in requested:
            continue
        count += conn.execute(routes.delete().where(*gateway.where(scope, row["scope"]),
            routes.c.session_key == row["session_key"])).rowcount
        if sid := entry_session_id(row["entry_json"]):
            gateway.retire_shared(conn, scope, route_namespace(row["session_key"]), [sid], now=time.time())
    return count


def insert_routes(conn, scope, wanted):
    sessions.lock_store(conn, scope, exclusive=True)
    count = 0
    for namespace, key, entry, updated in wanted:
        if gateway.route_retired(conn, scope, key, entry, time.time()):
            continue
        count += conn.execute(insert(routes).values(store_id=scope.require_store_id(), scope=namespace,
            session_key=key, entry_json=entry, updated_at=updated)
            .on_conflict_do_nothing(index_elements=list(routes.primary_key.columns))).rowcount
    return count


def _topic_where(table, scope, profile, chat, thread=None):
    clauses = [table.c.store_id == scope.require_store_id(), table.c.profile_name == profile, table.c.chat_id == chat]
    return [*clauses, table.c.thread_id == thread] if thread is not None else clauses


def repair_topics(conn, scope, wanted):
    sessions.lock_store(conn, scope, exclusive=True)
    counts = {"bindings_relabelled": 0, "bindings_duplicates_removed": 0, "mode_rows_relabelled": 0}
    for requested in wanted:
        chat, thread = str(requested["chat_id"]), str(requested["thread_id"])
        row = conn.execute(select(bindings).where(*_topic_where(bindings, scope, "default", chat, thread))).mappings().first()
        target = session_key_profile(row["session_key"]) if row else None
        if target in (None, "default"):
            continue
        collision = conn.scalar(select(bindings.c.thread_id).where(*_topic_where(bindings, scope, target, chat, thread)))
        statement = bindings.delete() if collision else bindings.update().values(profile_name=target)
        label = "bindings_duplicates_removed" if collision else "bindings_relabelled"
        counts[label] += conn.execute(statement.where(*_topic_where(bindings, scope, "default", chat, thread))).rowcount
        if conn.scalar(select(modes.c.chat_id).where(*_topic_where(modes, scope, target, chat))) is None:
            counts["mode_rows_relabelled"] += conn.execute(modes.update().where(*_topic_where(modes, scope, "default", chat))
                .values(profile_name=target)).rowcount
    return counts
