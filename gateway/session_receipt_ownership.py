"""Validate stored receipt ownership, including a native dataset moved with its profile."""
from hermes_db.health import is_postgresql_store, persisted_profile_id
from hermes_state_runtime import RuntimeStoreError


def validate_receipt_profile(authority, receipt):
    """A PG dataset keeps its store id; a moved native receipt must match this store's row and route."""
    if receipt.get("profile_id") == persisted_profile_id(authority):
        return
    if is_postgresql_store(authority.db):
        raise RuntimeStoreError("profile_mismatch")
    entry = receipt.get("entry") or {}
    origin = entry.get("origin") or {}
    registry = getattr(authority.runner, "session_authorities", None)
    profile = registry.profile_name(authority) if registry is not None else None
    sid = receipt.get("session_id")
    row = authority.db.get_session(sid)
    if (row is None or origin.get("profile") != profile
            or entry.get("session_id") != sid
            or not receipt.get("route")
            or receipt["route"] != entry.get("session_key")
            or (row["session_key"], row["chat_id"], row["user_id"]) != (
                receipt["route"], origin.get("chat_id"), origin.get("user_id"))):
        raise RuntimeStoreError("profile_mismatch")
