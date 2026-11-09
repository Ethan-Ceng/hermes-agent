"""Constructor, lifecycle and metadata mutations with stable lineage locks."""

import json
import time

from sqlalchemy import insert, or_, select

from hermes_db.domains.sessions.postgres.queries import prompts, sessions as repo
from hermes_db.tables.conversations import sessions
from hermes_db.core.values import encode_config, encode_text, explicit_fork, model_config, model_markers

_CREATION_FIELDS = ("model", "user_id", "session_key", "chat_id", "chat_type", "thread_id", "parent_session_id",
                    "cwd", "profile_name", "transport_profile", "git_repo_root", "origin_json", "display_name")
_PARENT_META = ("cwd", "git_repo_root", "git_branch")
_PARENT_ROUTING = ("user_id", "session_key", "chat_id", "chat_type", "thread_id", "display_name", "origin_json", "transport_profile")


def create_on_connection(conn, scope, session_id, source, *, own_profile=None, **values):
    from hermes_db.domains.runtime.values import RuntimeStoreError

    unsupported = set(values) - set(_CREATION_FIELDS) - {"model_config", "system_prompt"}
    if unsupported:
        raise TypeError("Unexpected session creation field")
    repo.lock_store(conn, scope, exclusive=bool(values.get("parent_session_id")))
    existing = repo.raw_session(conn, scope, session_id)
    parent = repo.raw_session(conn, scope, values.get("parent_session_id")) if values.get("parent_session_id") else None
    root_ids = {session_id}
    root_ids.update(row["lineage_root_id"] for row in (existing, parent) if row)
    for root_id in sorted(root_ids):
        repo.create_root(conn, scope, root_id)
        repo.lock_root(conn, scope, root_id)
    existing = repo.raw_session(conn, scope, session_id)
    if existing is None and repo.retired_session(conn, scope, session_id):
        raise RuntimeStoreError("not_found")
    parent = repo.raw_session(conn, scope, values.get("parent_session_id")) if values.get("parent_session_id") else None
    encoded = {field: values.get(field) for field in _CREATION_FIELDS}
    encoded.update(source=source, created_source=source, model_config=encode_config(values.get("model_config")))
    encoded["profile_name"] = encoded["profile_name"] or own_profile
    if parent:
        for field in _PARENT_META:
            if encoded.get(field) is None:
                encoded[field] = parent.get(field)
        if encoded["profile_name"] is None and _same_namespace(parent["session_key"], encoded["session_key"]):
            encoded["profile_name"] = parent["profile_name"]
    encoded["display_name"] = encode_text(encoded["display_name"]) if encoded["display_name"] is not None else None
    continuation = bool(parent and parent["end_reason"] == "compression" and not explicit_fork(encoded)
                        and (source != 'subagent' or parent['source'] == 'subagent'))
    config = model_config(encoded["model_config"])
    inherit_routing = parent and parent["end_reason"] == "compression" and source != "tool" and all(
        config.get(marker) != parent["id"] for marker in ("_branched_from", "_delegate_from"))
    if inherit_routing:
        for field in _PARENT_ROUTING:
            if encoded.get(field) is None:
                encoded[field] = parent[field]
    encoded["system_prompt_hash"] = prompts.store_prompt(conn, scope, values.get("system_prompt"))
    if existing:
        update = _merge_constructor(existing, encoded)
        if existing["parent_session_id"] is None and encoded["parent_session_id"] and continuation:
            from hermes_db.domains.sessions.postgres.queries.leases import merge_turn_roots
            merge_turn_roots(conn, scope, existing["lineage_root_id"], parent["lineage_root_id"], time.time())
            update["lineage_root_id"] = parent["lineage_root_id"]
            conn.execute(sessions.update().where(sessions.c.store_id == scope.require_store_id(),
                sessions.c.lineage_root_id == existing["lineage_root_id"]).values(lineage_root_id=parent["lineage_root_id"]))
        repo.update_session(conn, scope, session_id, update)
    else:
        encoded.update(store_id=scope.require_store_id(), id=session_id, started_at=time.time(),
                       lineage_root_id=parent["lineage_root_id"] if continuation else session_id)
        conn.execute(insert(sessions).values(**encoded, **model_markers(encoded['model_config'])))
    _stamp_surface(conn, scope, session_id)
    if values.get("system_prompt") is not None:
        prompts.prune_prompts(conn, scope)
    return session_id


def _same_namespace(parent, child):
    if parent is None or child is None:
        return True
    def prefix(value):
        marker = value.find(":", 6)
        return value[:marker + 1] if marker >= 0 else value[:6]
    return prefix(parent) == prefix(child)


def _stamp_surface(conn, scope, session_id):
    from hermes_db.core.values import preferred_children

    current = repo.raw_session(conn, scope, session_id)
    surface = current["created_source"]
    unset = (None, "", "unknown", "local")
    if surface in unset:
        return
    unstamped = conn.scalar(select(sessions.c.id).where(sessions.c.store_id == scope.require_store_id(),
        sessions.c.lineage_root_id == current["lineage_root_id"], sessions.c.id != session_id,
        or_(sessions.c.created_source.is_(None), sessions.c.created_source.in_(unset[1:]))).limit(1))
    if unstamped is None:
        return
    rows = repo.lineage_rows(conn, scope, session_id)
    by_id = {row["id"]: row for row in rows}
    preferred = preferred_children(rows)
    seen = set()
    while current["parent_session_id"] in by_id:
        parent = by_id[current["parent_session_id"]]
        if parent["id"] in seen or parent["end_reason"] != "compression" or preferred.get(parent["id"]) != current["id"]:
            return
        seen.add(parent["id"])
        if parent["created_source"] not in (*unset, surface):
            return
        if parent["created_source"] in unset:
            repo.update_session(conn, scope, parent["id"], {"created_source": surface})
        current = parent


def _merge_constructor(existing, incoming):
    values = {field: value for field, value in incoming.items() if existing.get(field) is None and value is not None}
    if existing["source"] == "unknown":
        values["source"] = incoming["source"]
    if existing.get("created_source") in (None, "", "unknown", "local") and incoming["source"] != "local":
        values["created_source"] = incoming["source"]
    old = model_config(existing.get("model_config"))
    if set(old) == {"_reset_from"} and incoming.get("model_config"):
        values["model_config"] = json.dumps(model_config(incoming["model_config"]) | old)
    return values


def create(transactions, scope, session_id, source, *, own_profile=None, **values):
    with transactions.write() as conn:
        return create_on_connection(conn, scope, session_id, source, own_profile=own_profile, **values)


def patch_model(conn, scope, session_id, patch, *, extra=None):
    row = repo.lock_session(conn, scope, session_id)
    if row is None:
        return
    config = model_config(row["model_config"])
    for key, value in patch.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    repo.update_session(conn, scope, session_id, {"model_config": encode_config(config), **(extra or {})})


def set_prompt(transactions, scope, session_id, value, *, tools=False):
    with transactions.write() as conn:
        if repo.lock_session(conn, scope, session_id) is None:
            return
        payload = json.dumps(value) if tools and value is not None else value
        digest = prompts.store_prompt(conn, scope, payload)
        values = {"tool_names": digest} if tools else {"system_prompt_hash": digest, "system_prompt": None}
        repo.update_session(conn, scope, session_id, values)
        prompts.prune_prompts(conn, scope)


def end(transactions, scope, session_id, reason):
    with transactions.write() as conn:
        row = repo.lock_session(conn, scope, session_id)
        if row is not None and row["ended_at"] is None:
            repo.update_session(conn, scope, session_id, {"ended_at": time.time(), "end_reason": reason})
            repo.bump_generation(conn, scope, row, reason)


def lineage_flag(conn, scope, session_id, field, value, *, extra=None):
    if repo.lock_session(conn, scope, session_id) is None:
        return []
    ids = [row["id"] for row in repo.lineage_rows(conn, scope, session_id)]
    conn.execute(sessions.update().where(sessions.c.store_id == scope.require_store_id(), sessions.c.id.in_(ids))
                 .values(**{field: value, **(extra or {})}))
    return ids


def reopen(transactions, scope, session_id):
    with transactions.write() as conn:
        if repo.lock_session(conn, scope, session_id) is None:
            return
        retire_queued_on_connection(conn, scope, session_id)
        repo.update_session(conn, scope, session_id, {"ended_at": None, "end_reason": None})
        rows = repo.lineage_rows(conn, scope, session_id)
        if not any(row["archived"] and not row["auto_archived"] for row in rows):
            lineage_flag(conn, scope, session_id, "archived", 0, extra={"auto_archived": 0})


def retire_queued_on_connection(conn, scope, session_id):
    from hermes_db.tables.conversations import messages
    from hermes_db.domains.sessions.rules import QUEUED_PROMPT_METADATA_KEY

    rows = conn.execute(select(messages.c.id, messages.c.display_metadata).where(
        messages.c.store_id == scope.require_store_id(), messages.c.session_id == session_id,
        messages.c.role == "user", messages.c.active == 1)).mappings()
    ids = [row["id"] for row in rows if model_config(row["display_metadata"]).get(QUEUED_PROMPT_METADATA_KEY)]
    if not ids:
        return 0
    changed = conn.execute(messages.update().where(messages.c.store_id == scope.require_store_id(), messages.c.id.in_(ids))
                           .values(active=0)).rowcount
    repo.update_session(conn, scope, session_id, {
        "transcript_revision": sessions.c.transcript_revision + changed,
        "transcript_edit_revision": sessions.c.transcript_edit_revision + changed})
    return changed
