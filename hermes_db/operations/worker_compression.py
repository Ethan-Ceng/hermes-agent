"""Closed Worker archive/flush/rotation handlers on the receipt connection."""

import json
import math

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import compression, compression_publish, messages as transcript
from hermes_db.operations.worker_handlers import _fields
from hermes_db.domains.sessions.postgres.queries import messages, sessions
from hermes_db.repositories import runtime, workers
from hermes_db.tables.conversations import messages as message_table
from hermes_db.tables.runtime import worker_executions
from hermes_db.core.values import model_config
from hermes_state_runtime import HANDOFF_MESSAGE_FIELDS, RuntimeStoreError, _text, row_annotations
from hermes_state_worker_context import SIDECAR_KEYS


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RuntimeStoreError("invalid_params")
    return value


def handoff(conn, scope, session_id, batch):
    if not isinstance(batch, list) or len(batch) > 1000:
        raise RuntimeStoreError("invalid_params")
    for message in batch:
        if (not isinstance(message, dict) or set(message) - HANDOFF_MESSAGE_FIELDS
                or message.get("role") not in ("user", "assistant", "system", "tool")):
            raise RuntimeStoreError("invalid_params")
        if "_row_id" in message and messages.one(conn, scope, session_id, message["_row_id"]) is None:
            raise RuntimeStoreError("permission_denied")


def watermarks(payload):
    for name in ("watermark", "watermark_ceiling"):
        value = payload.get(name)
        if value is not None and (type(value) is not int or value < 0):
            raise RuntimeStoreError("invalid_params")


def watermark(conn, scope, session_id, payload):
    from sqlalchemy import func
    _fields(payload, ())
    return {"value": conn.scalar(select(func.coalesce(func.max(message_table.c.id), 0)).where(
        messages.where(scope, [session_id]), message_table.c.active == 1))}


def archive(conn, scope, session_id, payload):
    _fields(payload, ("messages", "model_config_patch", "watermark", "lock_holder", "tail_count"),
        ("carried_messages", "covered_ids", "unresolved_held", "held_for_cas"))
    handoff(conn, scope, session_id, payload["messages"])
    watermarks(payload)
    for name in ("carried_messages", "unresolved_held", "held_for_cas"):
        value = payload.get(name)
        if value is not None and (not isinstance(value, list) or any(not isinstance(row, dict) for row in value)):
            raise RuntimeStoreError("invalid_params")
    covered = payload.get("covered_ids")
    if covered is not None and (not isinstance(covered, list) or any(type(rid) is not int or rid <= 0 for rid in covered)):
        raise RuntimeStoreError("invalid_params")
    patch = payload["model_config_patch"]
    if patch is not None and (not isinstance(patch, dict) or set(patch) - SIDECAR_KEYS):
        raise RuntimeStoreError("invalid_params")
    if payload["lock_holder"] is not None:
        _text(payload["lock_holder"])
    if type(payload["tail_count"]) is not int or payload["tail_count"] < 0:
        raise RuntimeStoreError("invalid_params")
    count = compression.compact_on_connection(conn, scope, session_id, payload["messages"],
        **{key: value for key, value in payload.items() if key != "messages"})
    return {"value": count, "annotations": row_annotations(payload["messages"])}


def append(conn, scope, session_id, payload):
    _fields(payload, ("messages", "compression_lock_holder", "turn_lease_holder", "turn_lease_ttl_seconds"))
    handoff(conn, scope, session_id, payload["messages"])
    for key in ("compression_lock_holder", "turn_lease_holder"):
        if payload[key] is not None:
            _text(payload[key])
    if not 0.1 <= number(payload["turn_lease_ttl_seconds"]) <= 3600:
        raise RuntimeStoreError("invalid_params")
    count = transcript.append_on_connection(conn, scope, session_id, payload["messages"],
        **{key: value for key, value in payload.items() if key != "messages"})
    return {"count": count, "annotations": row_annotations(payload["messages"])}


def _publish_config(parent, payload):
    for key in ("source", "cwd", "profile_name"):
        if payload[key] is not None and payload[key] != parent[key]:
            raise RuntimeStoreError("permission_denied")
    for key in ("model", "system_prompt"):
        if payload[key] is not None and not isinstance(payload[key], str):
            raise RuntimeStoreError("invalid_params")
    config = payload["model_config"]
    if config is not None and not isinstance(config, dict):
        raise RuntimeStoreError("invalid_params")
    config, prior = dict(config or {}), model_config(parent["model_config"])
    for key in ("_branched_from", "_delegate_from", "_reset_from"):
        if key in config and config[key] != prior.get(key):
            raise RuntimeStoreError("permission_denied")
        if key in prior:
            config[key] = prior[key]
    return config


def publish(conn, scope, session_id, payload):
    _fields(payload, ("child_session_id", "source", "messages", "model", "model_config", "system_prompt", "cwd",
        "profile_name", "compression_lock_holder", "require_compression_lease", "require_lease_refresh",
        "lease_ttl_seconds", "watermark", "watermark_ceiling"))
    child = _text(payload["child_session_id"])
    _text(payload["compression_lock_holder"])
    watermarks(payload)
    if payload["require_compression_lease"] is not True or type(payload["require_lease_refresh"]) is not bool:
        raise RuntimeStoreError("invalid_params")
    if not 0.1 <= number(payload["lease_ttl_seconds"]) <= 3600:
        raise RuntimeStoreError("invalid_params")
    handoff(conn, scope, session_id, payload["messages"])
    parent = sessions.get_session(conn, scope, session_id)
    config = _publish_config(parent, payload)
    if sessions.raw_session(conn, scope, child) is not None:
        raise RuntimeStoreError("permission_denied")
    worker = conn.execute(select(worker_executions).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id == session_id, worker_executions.c.status.in_(("registered", "running")))).mappings().one_or_none()
    if worker is None:
        raise RuntimeStoreError("stale_generation")
    compression_publish.publish_on_connection(conn, scope, parent_session_id=session_id,
        **dict(payload, model_config=config))
    _migrate_automation(conn, scope, session_id, child)
    sessions.update_session(conn, scope, child, {"runtime_generation": worker["generation"]})
    conn.execute(worker_executions.update().where(*workers.where(scope, worker["execution_id"])).values(session_id=child))
    linked = workers.linked_admission(conn, scope, session_id, worker["generation"], worker["owner_epoch"], ("started", "unknown"))
    if linked:
        lineage = json.loads(linked["lineage_json"])
        if lineage[-1] == session_id:
            runtime.update(conn, scope, linked["admission_id"], lineage_json=json.dumps([*lineage, child], separators=(",", ":")))
    return {"value": None, "worker_assignment": {"parent": session_id, "session_id": child},
            "annotations": row_annotations(payload["messages"])}


def _migrate_automation(conn, scope, parent, child):
    from hermes_cli.goals import GoalState
    from hermes_cli.heartbeat import HeartbeatState
    from hermes_cli.loops import LoopState

    for family, state_type in (("goal", GoalState), ("heartbeat", HeartbeatState), ("loop", LoopState)):
        old_key, new_key = f"{family}:{parent}", f"{family}:{child}"
        raw = runtime.meta(conn, scope, old_key)
        if raw is None:
            continue
        state = state_type.from_json(raw)
        if state.status == "cleared":
            continue
        prior = runtime.meta(conn, scope, new_key)
        if prior is not None and (family != "heartbeat" or state_type.from_json(prior).status != "cleared"):
            continue
        runtime.set_meta(conn, scope, new_key, state.to_json())
        state.status = "cleared"
        runtime.set_meta(conn, scope, old_key, state.to_json())
