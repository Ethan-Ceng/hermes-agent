"""Scoped session records, lineage locks, and detached business row mappings."""

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.conversations import sessions, system_prompts, transcript_roots
from hermes_db.tables.runtime import state_meta
from hermes_db.core.values import decode_text, model_config, model_markers, preferred_children

_TEXT_BYTES = ("system_prompt", "display_name", "title", "last_activity_description", "handoff_error", "compression_failure_error")


def where_session(scope, session_id):
    return and_(sessions.c.store_id == scope.require_store_id(), sessions.c.id == session_id)


def raw_session(conn, scope, session_id):
    row = conn.execute(select(sessions).where(where_session(scope, session_id))).mappings().one_or_none()
    return dict(row) if row else None


def lock_store(conn, scope, *, exclusive=False):
    """Share the lineage-map fence during writes; parent backfills hold it exclusively."""
    key = "hermes:lineage-map-lock"
    statement = select(state_meta.c.key).where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key == key)
    locked = statement.with_for_update(read=not exclusive)
    if conn.scalar(locked) is None:
        conn.execute(insert(state_meta).values(store_id=scope.require_store_id(), key=key)
                     .on_conflict_do_nothing(index_elements=list(state_meta.primary_key.columns)))
        conn.execute(locked).one()


def create_root(conn, scope, root_id):
    conn.execute(insert(transcript_roots).values(store_id=scope.require_store_id(), root_id=root_id)
                 .on_conflict_do_nothing(index_elements=[transcript_roots.c.store_id, transcript_roots.c.root_id]))


def lock_root(conn, scope, root_id):
    conn.execute(select(transcript_roots.c.root_id).where(
        transcript_roots.c.store_id == scope.require_store_id(), transcript_roots.c.root_id == root_id).with_for_update()).one()


def lock_session(conn, scope, session_id):
    lock_store(conn, scope)
    row = raw_session(conn, scope, session_id)
    if row is not None:
        lock_root(conn, scope, row["lineage_root_id"])
        row = raw_session(conn, scope, session_id)
    return row


def get_session(conn, scope, session_id):
    return get_sessions(conn, scope, [session_id]).get(session_id)


def get_sessions(conn, scope, session_ids):
    prompt, tools = system_prompts.alias("prompt"), system_prompts.alias("tools")
    statement = select(sessions, prompt.c.prompt.label("resolved_prompt"), tools.c.prompt.label("resolved_tools"))
    statement = statement.outerjoin(prompt, and_(prompt.c.store_id == sessions.c.store_id,
                                                 prompt.c.hash == sessions.c.system_prompt_hash))
    statement = statement.outerjoin(tools, and_(tools.c.store_id == sessions.c.store_id, tools.c.hash == sessions.c.tool_names))
    rows = conn.execute(statement.where(sessions.c.store_id == scope.require_store_id(), sessions.c.id.in_(session_ids))).mappings()
    return {row["id"]: _resolved_row(row) for row in rows}


def _resolved_row(row):
    data = business_row(row)
    prompt_value = data.pop("resolved_prompt")
    data["system_prompt"] = decode_text(prompt_value) if prompt_value is not None else data["system_prompt"]
    tools_value = data.pop("resolved_tools")
    data["tool_names"] = decode_text(tools_value) if tools_value is not None else data["tool_names"]
    return data


def business_row(row):
    data = dict(row)
    for name in _TEXT_BYTES:
        if name in data:
            data[name] = decode_text(data[name])
    for name in ("store_id", "lineage_root_id", "title_search", "delegate_origin", "has_delegate_marker", "has_branch_marker"):
        data.pop(name, None)
    config = model_config(data.get("model_config"))
    for name in ("_reset_from", "_branched_from"):
        value = config.get(name)
        if isinstance(value, str) and value.strip():
            data[name] = value.strip()
    return data


def update_session(conn, scope, session_id, values, *conditions):
    if not values:
        return 0
    if 'model_config' in values:
        values = {**values, **model_markers(values['model_config'])}
    return conn.execute(update(sessions).where(where_session(scope, session_id), *conditions).values(**values)).rowcount


def lineage_rows(conn, scope, session_id):
    from hermes_db.domains.sessions.postgres.queries.session_queries import last_activity

    row = raw_session(conn, scope, session_id)
    if row is None:
        return []
    return [dict(item) for item in conn.execute(select(sessions, last_activity(conn).label("_chain_activity")).where(
        sessions.c.store_id == scope.require_store_id(), sessions.c.lineage_root_id == row["lineage_root_id"])
        .order_by(sessions.c.started_at, sessions.c.id)).mappings()]


def compression_tip(conn, scope, session_id):
    rows = lineage_rows(conn, scope, session_id)
    children = preferred_children(rows)
    current, seen = session_id, set()
    while current in children:
        if current in seen:
            from hermes_db.errors import StorageWriteError
            raise StorageWriteError("Conversation lineage contains a cycle")
        seen.add(current)
        current = children[current]
    return current


def retired_session(conn, scope, session_id):
    from hermes_db.domains.runtime.receipts import RETIRED_PREFIX

    return conn.scalar(select(state_meta.c.key).where(state_meta.c.store_id == scope.require_store_id(),
                                                     state_meta.c.key == RETIRED_PREFIX + session_id)) is not None


def bump_generation(conn, scope, row, reason):
    from hermes_db.domains.sessions.rules import _RESET_END_REASONS
    from hermes_db.tables.gateway import conversation_generations as generations

    source, key = (str(row.get(name) or "").strip() for name in ("source", "session_key"))
    if reason not in _RESET_END_REASONS or not source or not key:
        return
    statement = insert(generations).values(store_id=scope.require_store_id(), source=source,
                                           session_key=key, generation=1)
    conn.execute(statement.on_conflict_do_update(index_elements=list(generations.primary_key.columns),
                                                 set_={"generation": generations.c.generation + 1}))
