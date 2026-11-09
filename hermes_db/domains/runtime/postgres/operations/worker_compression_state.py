"""Closed compression guard/cleanup verbs, with scoped holder checks."""

from functools import partial

from hermes_db.domains.sessions.postgres.operations import compression_state, leases as operations
from hermes_db.domains.runtime.postgres.operations.worker_compression import number
from hermes_db.domains.runtime.postgres.operations.worker_compression_reads import ReadView
from hermes_db.domains.runtime.postgres.operations.worker_handlers import _fields
from hermes_db.domains.sessions.postgres.queries import leases, sessions
from hermes_db.tables.gateway import compression_locks, session_turn_leases
from hermes_state_runtime import RuntimeStoreError, _text


def lock(conn, scope, session_id, payload, *, action):
    if action == "holder":
        _fields(payload, ())
        return {"value": operations.compression_holder(conn, scope, session_id)}
    _fields(payload, ("holder",), () if action == "release" else ("ttl_seconds",))
    holder = _text(payload["holder"])
    ttl = number(payload.get("ttl_seconds", 300))
    if not 0.1 <= ttl <= 3600:
        raise RuntimeStoreError("invalid_params")
    return {"value": operations.change(conn, scope, session_id, holder, action, ttl_seconds=ttl)}


def cooldown_record(conn, scope, session_id, payload):
    _fields(payload, ("cooldown_until", "error"))
    number(payload["cooldown_until"])
    if payload["error"] is not None and not isinstance(payload["error"], str):
        raise RuntimeStoreError("invalid_params")
    compression_state.record_cooldown(conn, scope, session_id, payload["cooldown_until"], payload["error"])
    return {"value": None}


def cooldown_restore(conn, scope, session_id, payload):
    _fields(payload, ("snapshot",))
    saved = payload["snapshot"]
    _fields(saved, ("session_exists", "cooldown_until", "error"))
    if type(saved["session_exists"]) is not bool:
        raise RuntimeStoreError("invalid_params")
    if saved["cooldown_until"] is not None:
        number(saved["cooldown_until"])
    if saved["error"] is not None and not isinstance(saved["error"], str):
        raise RuntimeStoreError("invalid_params")
    compression_state.restore_cooldown(conn, scope, session_id, saved)
    return {"value": None}


def cooldown_clear(conn, scope, session_id, payload):
    _fields(payload, ())
    compression_state.restore_cooldown(conn, scope, session_id, {
        "session_exists": True, "cooldown_until": None, "error": None})
    return {"value": None}


def counter(conn, scope, session_id, payload, *, column):
    _fields(payload, ("value",))
    value = payload["value"]
    if value is not None:
        number(value)
    if column != "compression_recovery_deadline" and (type(value) is not int or value < 0):
        raise RuntimeStoreError("invalid_params")
    sessions.update_session(conn, scope, session_id, {column: value})
    return {"value": None}


def reopen(conn, scope, session_id, payload):
    _fields(payload, ())
    return {"value": compression_state.reopen(conn, scope, session_id, orphan=True)}


def cleanup(conn, scope, session_id, payload, *, turn=False):
    _fields(payload, ("target", "holder"))
    target, holder = _text(payload["target"]), _text(payload["holder"])
    ReadView(conn, scope).authorize(session_id, target)
    root = sessions.raw_session(conn, scope, session_id)["lineage_root_id"]
    if root != sessions.raw_session(conn, scope, target)["lineage_root_id"]:
        raise RuntimeStoreError("permission_denied")
    table, column, key = (session_turn_leases, "conversation_id", root) if turn else (compression_locks, "session_id", target)
    leases.release(conn, scope, table, column, key, holder)
    return {"released": True} if turn else {"value": None}


def handlers():
    from hermes_db.domains.runtime.postgres.operations import worker_compression as writes, worker_compression_reads as reads
    values = {"turn.cleanup": partial(cleanup, turn=True), "compression.cleanup": cleanup,
        "compression.reopen": reopen, "compression.append": writes.append, "compression.archive": writes.archive,
        "compression.publish": writes.publish, "compression.watermark": writes.watermark,
        "compression.context": reads.context, "compression.lineage": reads.lineage,
        "compression.boundary": reads.boundary, "compression.history": reads.history,
        "compression.cooldown.record": cooldown_record, "compression.cooldown.restore": cooldown_restore,
        "compression.cooldown.clear": cooldown_clear}
    values.update({"compression.lock." + action: partial(lock, action=action) for action in ("acquire", "renew", "release", "holder")})
    values.update({"compression." + name: partial(counter, column=column) for name, column in (
        ("fallback", "compression_fallback_streak"), ("ineffective", "compression_ineffective_count"),
        ("recovery", "compression_recovery_deadline"))})
    return values
