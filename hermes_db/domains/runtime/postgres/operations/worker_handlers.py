"""Closed worker operations; every handler uses the receipt's Core connection."""

import json
from functools import partial

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import messages as transcript, sessions as lifecycle
from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
from hermes_db.domains.sessions.postgres.queries import messages, prompts, sessions, usage
from hermes_db.tables.conversations import messages as message_table
from hermes_db.core.values import encode_config, model_config
from hermes_state_runtime import RuntimeStoreError, _MESSAGE_FIELDS, _text, row_annotations
from hermes_state_worker_context import SIDECAR_KEYS


def _fields(payload, required, optional=()):
    if not isinstance(payload, dict) or set(payload) - set(required) - set(optional) or set(required) - set(payload):
        raise RuntimeStoreError("invalid_params")


def context(conn, scope, session_id, payload):
    _fields(payload, ())
    return {"session": sessions.get_session(conn, scope, session_id)}


def prompt(conn, scope, session_id, payload):
    _fields(payload, ("system_prompt",))
    value = payload["system_prompt"]
    if value is not None and not isinstance(value, str):
        raise RuntimeStoreError("invalid_params")
    sessions.update_session(conn, scope, session_id, {"system_prompt_hash": prompts.store_prompt(conn, scope, value), "system_prompt": None})
    prompts.prune_prompts(conn, scope)
    return {"value": None}


def sidecars(conn, scope, session_id, payload):
    _fields(payload, ("patch",))
    patch = payload["patch"]
    if not isinstance(patch, dict) or set(patch) - SIDECAR_KEYS:
        raise RuntimeStoreError("invalid_params")
    config = model_config(sessions.raw_session(conn, scope, session_id)["model_config"])
    for key, value in patch.items():
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
    sessions.update_session(conn, scope, session_id, {"model_config": encode_config(config)})
    return {"value": None}


def tools(conn, scope, session_id, payload):
    _fields(payload, ("tool_names",))
    pin = payload["tool_names"]
    if pin is not None:
        _validate_pin(pin)
    encoded = None if pin is None else json.dumps(pin)
    if encoded is not None and len(encoded) > 4 * 1024 * 1024:
        raise RuntimeStoreError("invalid_params")
    sessions.update_session(conn, scope, session_id, {"tool_names": prompts.store_prompt(conn, scope, encoded)})
    prompts.prune_prompts(conn, scope)
    return {"value": None}


def _validate_pin(pin):
    if isinstance(pin, list):
        if all(isinstance(name, str) and 0 < len(name) <= 256 for name in pin):
            return
    elif isinstance(pin, dict):
        backend = pin.get("delegation_backend", "")
        if {"version", "tools"} <= set(pin) <= {"version", "tools", "delegation_backend"} and (
                isinstance(pin["version"], str) and isinstance(pin["tools"], list) and isinstance(backend, str) and len(backend) <= 64):
            return
    raise RuntimeStoreError("invalid_params")


def tail_role(conn, scope, session_id, payload):
    _fields(payload, ())
    value = conn.scalar(select(message_table.c.role).where(messages.where(scope, [session_id]), message_table.c.active == 1,
        message_table.c.role.not_in(("session_meta", "system"))).order_by(message_table.c.id.desc()).limit(1))
    return {"value": value}


def row_role(conn, scope, session_id, payload):
    _fields(payload, ("row_id",))
    if type(payload["row_id"]) is not int:
        raise RuntimeStoreError("invalid_params")
    value = conn.scalar(select(message_table.c.role).where(messages.where(scope, [session_id]),
        message_table.c.id == payload["row_id"], message_table.c.active == 1))
    return {"value": value}


def append(conn, scope, session_id, payload):
    _fields(payload, ("messages",), ("turn_lease_holder",))
    batch = payload["messages"]
    if not isinstance(batch, list) or len(batch) > 1000:
        raise RuntimeStoreError("invalid_params")
    for msg in batch:
        if not isinstance(msg, dict) or set(msg) - _MESSAGE_FIELDS or msg.get("role") not in ("user", "assistant", "system", "tool"):
            raise RuntimeStoreError("invalid_params")
        if "_row_id" in msg and messages.one(conn, scope, session_id, msg["_row_id"]) is None:
            raise RuntimeStoreError("permission_denied")
    holder = payload.get("turn_lease_holder")
    if holder is not None:
        _text(holder)
    count = transcript.append_on_connection(conn, scope, session_id, batch, turn_lease_holder=holder)
    return {"count": count, "annotations": row_annotations(batch)}


def finish(conn, scope, session_id, payload):
    _fields(payload, ())
    return {"status": "terminal"}


def usage_main(conn, scope, session_id, payload, *, auxiliary=False):
    from hermes_state_usage import _MODEL_USAGE_FIELDS, _TOKEN_COUNTERS
    source = payload.get("source") if not auxiliary else None
    payload = dict(payload)
    if not auxiliary:
        payload.pop("source", None)
    allowed = (_MODEL_USAGE_FIELDS - {"billing_mode", "actual_cost_usd", "cost_status", "cost_source"} | {"task"}) if auxiliary else (
        _MODEL_USAGE_FIELDS | {"pricing_version", "absolute", "task"})
    if set(payload) - allowed:
        raise RuntimeStoreError("invalid_params")
    for key, value in payload.items():
        if key in (*_TOKEN_COUNTERS, "api_call_count"):
            valid = type(value) is int and 0 <= value <= 2**53
        elif key in ("estimated_cost_usd", "actual_cost_usd"):
            valid = value is None or type(value) in (int, float) and 0 <= value <= 1e12
        elif key == "absolute":
            valid = type(value) is bool
        else:
            valid = value is None or isinstance(value, str) and len(value) <= 4096
        if not valid:
            raise RuntimeStoreError("invalid_params")
    if auxiliary:
        if not payload.get("task"):
            raise RuntimeStoreError("invalid_params")
        usage.record_route(conn, scope, session_id, {"api_call_count": 1, **payload}, task=payload["task"])
    else:
        usage.update_totals(conn, scope, session_id, payload)
        from gateway.session_policy import created_surface
        surfaced = created_surface(source) if isinstance(source, str) else None
        row = sessions.raw_session(conn, scope, session_id)
        if surfaced and row["created_source"] in (None, "", "unknown", "local"):
            sessions.update_session(conn, scope, session_id, {"created_source": surfaced})
            lifecycle._stamp_surface(conn, scope, session_id)
    return {"value": None}


def handlers(metrics_policy=None):
    from hermes_db.domains.runtime.postgres.operations import worker_lifecycle as life
    from hermes_db.domains.runtime.postgres.operations.worker_compression_state import handlers as compression_handlers
    from hermes_db.domains.runtime.postgres.operations.worker_turn import turn
    from hermes_db.domains.runtime.postgres.operations.worker_domains import write_handlers
    values = {"session.context": context, "session.prompt": prompt, "session.sidecars": sidecars,
              "session.tools": tools, "session.tail_role": tail_role, "session.row_role": row_role,
              "transcript.append": append, "execution.finish": finish, "usage.main": usage_main,
              "usage.auxiliary": partial(usage_main, auxiliary=True),
              "session.create": life.create, "session.end": life.end, "session.lifecycle": life.status,
              "session.title": life.title, "session.title_source": life.title_source, "session.next_title": life.next_title,
              "session.activity": life.activity, "session.activity_clear": life.activity_clear,
              "session.billing_route": life.billing_route, "session.api_content": life.api_content,
              "session.message_api_content": partial(life.api_content, addressed=True), "session.user_content": life.user_content}
    values.update({"turn." + action: partial(turn, action=action) for action in ("acquire", "renew", "release")})
    values.update(compression_handlers())
    values.update(write_handlers(metrics_policy))
    return {name: CoreEffect(function) for name, function in values.items()}
