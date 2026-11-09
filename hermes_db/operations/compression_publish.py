"""Publish a compression child and advance durable routing in one transaction."""

from collections import deque
from copy import deepcopy
import json
import time

from hermes_cli.timefmt import coerce_epoch
from hermes_db.message_codec import codec
from hermes_db.operations import compression, messages as writes, sessions as lifecycle
from hermes_db.repositories import compression as repo, messages as transcript, sessions
from hermes_db.repositories.lineage import advance_local_target
from hermes_db.tables.conversations import messages as table
from hermes_db.core.values import model_config
from hermes_state_messages import _parse_tool_calls, _scrub_surrogates, _tool_calls_len


def publish(transactions, scope, *, messages, own_profile=None, **options):
    writes._stamp_logical_identities(messages)
    work = deepcopy(messages)
    with transactions.write() as conn:
        publish_on_connection(conn, scope, messages=work, own_profile=own_profile, **options)
    writes._publish_stamps(messages, work)


def publish_on_connection(conn, scope, *, parent_session_id, child_session_id, source, messages: list,
        model=None, model_config=None, system_prompt=None, cwd=None, profile_name=None, own_profile=None,
        compression_lock_holder=None, require_compression_lease=True, require_lease_refresh=False,
        lease_ttl_seconds=300.0, watermark=None, watermark_ceiling=None):
    from hermes_state_common import is_automatic_end_reason
    from hermes_state_errors import CompressionSessionBusyError

    sessions.lock_store(conn, scope, exclusive=True)
    parent = sessions.lock_session(conn, scope, parent_session_id)
    if parent is None:
        raise RuntimeError("Compression parent not found")
    if require_compression_lease:
        compression.require_lease(conn, scope, parent_session_id, compression_lock_holder,
            error_type=CompressionSessionBusyError, refresh=require_lease_refresh, ttl=lease_ttl_seconds)
    elif require_lease_refresh and compression_lock_holder:
        from hermes_db.repositories.leases import renew
        from hermes_db.tables.gateway import compression_locks
        renew(conn, scope, compression_locks, "session_id", parent_session_id,
              compression_lock_holder, time.time() + lease_ttl_seconds)
    if parent["ended_at"] is not None and not is_automatic_end_reason(parent["end_reason"]):
        raise RuntimeError("Compression parent already ended")
    if not messages:
        raise RuntimeError("Compression child handoff must not be empty")
    if sessions.raw_session(conn, scope, child_session_id) is not None:
        raise RuntimeError("Compression child already exists")
    # The parent closure precedes the constructor only inside this transaction,
    # so root/routing inheritance follows the same continuation rules.
    sessions.update_session(conn, scope, parent_session_id, {"ended_at": time.time(), "end_reason": "compression"})
    create_child(conn, scope, parent, child_session_id=child_session_id, source=source, model=model,
        config=model_config, system_prompt=system_prompt, cwd=cwd, profile_name=profile_name, own_profile=own_profile)
    active = transcript.select_rows(conn, scope, [parent_session_id], table.c.active == 1)
    carry_timestamps(active, messages)
    count, tools = writes.insert_rows(conn, scope, child_session_id, messages)
    tail = [row for row in active if watermark is not None and row["id"] > int(watermark)
            and (watermark_ceiling is None or row["id"] <= int(watermark_ceiling))]
    repo.clone_rows(conn, scope, parent_session_id, [row["id"] for row in tail], target_session=child_session_id)
    sessions.update_session(conn, scope, child_session_id, {"message_count": count + len(tail),
        "tool_call_count": tools + sum(_tool_calls_len(row["tool_calls"]) for row in tail)})
    transcript.reconcile_orders(conn, scope, child_session_id)
    transcript.bump_revision(conn, scope, child_session_id)
    advance_local_target(conn, scope, parent_session_id, child_session_id)
    if parent["archived"]:
        _unarchive_automatic(conn, scope, child_session_id)


def create_child(conn, scope, parent, *, child_session_id, source, model=None, config=None,
                 system_prompt=None, cwd=None, profile_name=None, own_profile=None):
    from gateway.session_policy import created_surface

    continuation = not any(key in (config or {}) for key in ("_branched_from", "_reset_from"))
    carried = {key: value for key, value in model_config(parent["model_config"]).items()
               if continuation and key in ("onboarding_run", "prompt_refresh_epoch")}
    config = {**carried, **(config or {})}
    routing = {key: parent[key] for key in lifecycle._PARENT_ROUTING}
    # Constructor takes text for display_name, while repository rows hold BYTEA.
    from hermes_db.core.values import decode_text
    routing["display_name"] = decode_text(routing["display_name"])
    lifecycle.create_on_connection(conn, scope, child_session_id, source, own_profile=own_profile,
        parent_session_id=parent["id"], model=model, model_config=config, system_prompt=system_prompt,
        cwd=cwd or parent["cwd"], git_repo_root=parent["git_repo_root"],
        profile_name=profile_name or parent["profile_name"] or own_profile, **routing)
    sessions.update_session(conn, scope, child_session_id, {
        "git_branch": parent["git_branch"], "tool_names": parent["tool_names"],
        "created_source": created_surface(parent["created_source"]) or created_surface(source),
        "pinned": parent["pinned"] if continuation else 0,
        "archived": parent["archived"] if continuation else 0,
        "auto_archived": parent["auto_archived"] if continuation else 0})


def carry_timestamps(active, batch):
    donors = {}
    for row in active:
        key = (row["role"], row["content"], row["tool_call_id"], row["tool_calls"], row["tool_name"])
        donors.setdefault(key, deque()).append(row["timestamp"])
    for msg in batch:
        if coerce_epoch(msg.get("timestamp"), field="message timestamp") is not None:
            continue
        calls = _parse_tool_calls(msg.get("tool_calls"))
        key = (msg.get("role", "unknown"), codec._encode_content(msg.get("content")), msg.get("tool_call_id"),
               json.dumps(calls) if calls else None, _scrub_surrogates(msg.get("tool_name")))
        queue = donors.get(key)
        if queue:
            msg["timestamp"] = queue.popleft()


def _unarchive_automatic(conn, scope, session_id):
    rows = sessions.lineage_rows(conn, scope, session_id)
    if not any(row["archived"] and not row["auto_archived"] for row in rows):
        lifecycle.lineage_flag(conn, scope, session_id, "archived", 0, extra={"auto_archived": 0})
