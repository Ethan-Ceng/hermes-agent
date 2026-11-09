"""Closed constructor, metadata and sidecar operations in a worker receipt."""

import math
import time

from sqlalchemy import func, or_, select

from hermes_db.domains.sessions.postgres.support.message_codec import codec, content_to_bytes
from hermes_db.domains.sessions.postgres.operations import sessions as lifecycle, titles
from hermes_db.domains.runtime.postgres.operations.worker_handlers import _fields
from hermes_db.domains.sessions.postgres.queries import messages, sessions
from hermes_db.tables.conversations import messages as message_table, sessions as session_table
from hermes_db.tables.runtime import worker_executions, worker_receipts
from hermes_db.core.values import decode_text, encode_config, encode_text, model_config
from hermes_state_runtime import RuntimeStoreError
from hermes_state_worker_lifecycle import _CONSTRUCTOR_CONFIG, _CREATE_FIELDS, _IDENTITY_FIELDS, _row_id


def create(conn, scope, session_id, payload):
    if set(payload) - _CREATE_FIELDS or "source" not in payload:
        raise RuntimeStoreError("invalid_params")
    row = sessions.get_session(conn, scope, session_id)
    if row is None or payload["source"] != row["source"]:
        raise RuntimeStoreError("permission_denied")
    if any(payload.get(key) is not None and payload[key] != row[key] for key in _IDENTITY_FIELDS):
        raise RuntimeStoreError("permission_denied")
    if any(payload.get(key) is not None and not isinstance(payload[key], str) for key in _CREATE_FIELDS - {"model_config"}):
        raise RuntimeStoreError("invalid_params")
    config = payload.get("model_config")
    if config is not None and (not isinstance(config, dict) or set(config) - _CONSTRUCTOR_CONFIG):
        raise RuntimeStoreError("invalid_params")
    from hermes_constants import profile_name_for_home
    lifecycle.create_on_connection(conn, scope, session_id, own_profile=profile_name_for_home(scope.profile_home), **payload)
    if config and model_config(row["model_config"]).get("_delegate_from") is not None:
        current = model_config(sessions.raw_session(conn, scope, session_id)["model_config"])
        sessions.update_session(conn, scope, session_id, {"model_config": encode_config({**current, **config})})
    return {"value": session_id}


def end(conn, scope, session_id, payload):
    _fields(payload, ("end_reason",))
    reason = payload["end_reason"]
    if not isinstance(reason, str) or not reason:
        raise RuntimeStoreError("invalid_params")
    row = sessions.raw_session(conn, scope, session_id)
    if row["ended_at"] is None:
        sessions.update_session(conn, scope, session_id, {"ended_at": time.time(), "end_reason": reason})
        sessions.bump_generation(conn, scope, row, reason)
    return {"value": None}


def status(conn, scope, session_id, payload):
    from hermes_state_sessions import classify_session_status
    _fields(payload, ())
    row = conn.execute(select(message_table.c.role, message_table.c.tool_calls, message_table.c.finish_reason)
        .where(messages.where(scope, [session_id])).order_by(message_table.c.id.desc()).limit(1)).mappings().one_or_none()
    value = classify_session_status(role=row["role"], has_tool_calls=row["tool_calls"] is not None,
        finish_reason=row["finish_reason"]) if row else "empty"
    return {"value": value}


def title(conn, scope, session_id, payload):
    _fields(payload, ("title", "source"))
    if payload["source"] not in titles.RANK or payload["title"] is not None and not isinstance(payload["title"], str):
        raise RuntimeStoreError("invalid_params")
    try:
        value = bool(titles.set_title_on_connection(conn, scope, session_id, payload["title"], payload["source"]))
    except ValueError:
        return {"value": False, "error": "Title unavailable or invalid", "title_candidate": payload["title"]}
    return {"value": value}


def title_source(conn, scope, session_id, payload):
    _fields(payload, ("source",))
    if payload["source"] not in titles.RANK:
        raise RuntimeStoreError("invalid_params")
    return {"value": sessions.update_session(conn, scope, session_id, {"title_source": payload["source"]}, session_table.c.title.is_not(None)) > 0}


def next_title(conn, scope, session_id, payload):
    from hermes_state_titles import _NUMBERED_TITLE_RE
    _fields(payload, ("base_title",))
    candidate = payload["base_title"]
    if not isinstance(candidate, str):
        raise RuntimeStoreError("invalid_params")
    assigned = sessions.raw_session(conn, scope, session_id)["title"]
    encoded = candidate.encode("utf-8", "surrogatepass")
    attempted = conn.scalar(select(1).select_from(worker_receipts.join(worker_executions,
        (worker_receipts.c.store_id == worker_executions.c.store_id) & (worker_receipts.c.execution_id == worker_executions.c.execution_id)))
        .where(worker_receipts.c.store_id == scope.require_store_id(), worker_executions.c.session_id == session_id,
            worker_executions.c.status == "running", worker_receipts.c.title_candidate == encoded).limit(1))
    if candidate != decode_text(assigned) and attempted is None:
        raise RuntimeStoreError("permission_denied")
    match = _NUMBERED_TITLE_RE.match(candidate)
    base = match.group(1) if match else candidate
    # A candidate may be an invalid title. BYTEA comparison keeps its proof
    # lossless; only the sanitized text projection participates in prefix lookup.
    safe_base = base.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")
    rows = conn.execute(select(session_table.c.title).where(session_table.c.store_id == scope.require_store_id(),
        or_(session_table.c.title == base.encode("utf-8", "surrogatepass"),
            func.lower(session_table.c.title_search).startswith(safe_base.lower() + " #", autoescape=True)))).scalars().all()
    if not rows:
        return {"value": base}
    numbered = [_NUMBERED_TITLE_RE.match(decode_text(row)) for row in rows]
    return {"value": f"{base} #{max([1, *(int(item.group(2)) for item in numbered if item)]) + 1}"}


def activity(conn, scope, session_id, payload):
    from agent.session_activity import bound_activity_description, normalize_activity_provenance
    _fields(payload, ("ts", "description", "provenance"))
    if any(payload[key] is not None and not isinstance(payload[key], str) for key in ("description", "provenance")):
        raise RuntimeStoreError("invalid_params")
    when = payload["ts"]
    if when is not None and (type(when) not in (int, float) or not math.isfinite(when)):
        raise RuntimeStoreError("invalid_params")
    when = time.time() if when is None else float(when)
    sessions.update_session(conn, scope, session_id, {"last_activity_at": when,
        "last_activity_description": encode_text(bound_activity_description(payload["description"])),
        "last_activity_provenance": normalize_activity_provenance(payload["provenance"]).value},
        or_(session_table.c.last_activity_at.is_(None), session_table.c.last_activity_at < when))
    return {"value": None}


def activity_clear(conn, scope, session_id, payload):
    from agent.session_activity import ActivityProvenance
    _fields(payload, ())
    sessions.update_session(conn, scope, session_id, {"last_activity_description": b"", "last_activity_provenance": ActivityProvenance.UNKNOWN.value})
    return {"value": None}


def billing_route(conn, scope, session_id, payload):
    _fields(payload, ("provider", "base_url", "billing_mode"))
    if any(value is not None and not isinstance(value, str) for value in payload.values()):
        raise RuntimeStoreError("invalid_params")
    row = sessions.raw_session(conn, scope, session_id)
    sessions.update_session(conn, scope, session_id, {"billing_provider": payload["provider"], "billing_base_url": payload["base_url"],
        "billing_mode": payload["billing_mode"] if payload["billing_mode"] is not None else row["billing_mode"]})
    return {"value": None}


def api_content(conn, scope, session_id, payload, *, addressed=False):
    from hermes_state_messages import _scrub_surrogates
    _fields(payload, ("row_id", "content", "api_content") if addressed else ("content", "api_content"))
    if not isinstance(payload["api_content"], str):
        raise RuntimeStoreError("invalid_params")
    row_id = _row_id(payload) if addressed else conn.scalar(select(message_table.c.id).where(messages.where(scope, [session_id]),
        message_table.c.active == 1, message_table.c.role == "user").order_by(message_table.c.id.desc()).limit(1))
    row = messages.one(conn, scope, session_id, row_id) if row_id else None
    if not row or row["role"] != "user" or not row["active"] or content_to_bytes(row["content"]) != content_to_bytes(codec._encode_content(payload["content"])):
        return {"value": 0}
    return {"value": messages.update_row(conn, scope, session_id, row_id, {"api_content": _scrub_surrogates(payload["api_content"])})}


def user_content(conn, scope, session_id, payload):
    _fields(payload, ("row_id", "content"), ("display_metadata",))
    row_id = _row_id(payload)
    row = messages.one(conn, scope, session_id, row_id)
    if not row or row["role"] != "user" or not row["active"]:
        return {"value": 0}
    values = {"content": codec._encode_content(payload["content"])}
    if "display_metadata" in payload:
        from hermes_db.domains.sessions.postgres.support.message_codec import merge_display_metadata
        patch = codec._decode_display_metadata(codec._encode_display_metadata(payload['display_metadata'])) or {}
        metadata = merge_display_metadata(codec._decode_display_metadata(row['display_metadata']), patch)
        values.update(api_content=None, display_metadata=codec._encode_display_metadata(metadata))
    return {"value": messages.update_row(conn, scope, session_id, row_id, values)}
