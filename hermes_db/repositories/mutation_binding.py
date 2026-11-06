"""Existing control ownership over current rows, scoped to the selected store."""

from hermes_db.repositories import runtime, sessions
from hermes_state_mutation_binding import BINDING_PREFIX, _bindings_agree, _history_row, _owner_user, binding_names
from hermes_state_runtime import RuntimeStoreError, _json


def history_binding(conn, scope, session_id):
    return runtime.meta(conn, scope, BINDING_PREFIX + session_id)


def import_history_control(conn, scope, actor, session_ids):
    binding = _json([actor.profile_id, actor.subject])
    for sid in session_ids:
        if sessions.raw_session(conn, scope, sid) is None:
            runtime.set_meta(conn, scope, BINDING_PREFIX + sid, binding)


def authorize_history(conn, scope, actor, session_id, *, claim=False):
    from gateway.owner_identity import same_owner
    row = sessions.raw_session(conn, scope, session_id)
    if row is None or row["session_key"] or row["chat_id"] or row["origin_json"]:
        return False
    saved = history_binding(conn, scope, session_id)
    if saved is not None:
        if not binding_names(saved, actor.profile_id, actor.subject):
            raise RuntimeStoreError("permission_denied")
        return True
    if not _history_row(row):
        return False
    if _owner_user(row) and not same_owner(row["user_id"], actor.subject):
        raise RuntimeStoreError("permission_denied")
    if "session:create" not in actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    if claim:
        runtime.set_meta(conn, scope, BINDING_PREFIX + session_id, _json([actor.profile_id, actor.subject]))
    return True


def same_history_owner(conn, scope, anchor_id, session_id):
    from gateway.owner_identity import owners_agree

    anchor, row = (sessions.raw_session(conn, scope, sid) for sid in (anchor_id, session_id))
    if anchor is None or row is None:
        return False
    if row["session_key"] or row["chat_id"] or row["origin_json"]:
        return tuple(row[name] for name in ("user_id", "session_key", "chat_id")) == tuple(
            anchor[name] for name in ("user_id", "session_key", "chat_id"))
    binding = runtime.meta(conn, scope, BINDING_PREFIX + session_id)
    if not _bindings_agree(binding, runtime.meta(conn, scope, BINDING_PREFIX + anchor_id)):
        return False
    peer = row["source"] == anchor["source"] and not any(anchor[name] for name in ("session_key", "chat_id", "origin_json"))
    return binding is not None or ((_history_row(row) or peer)
        and (_owner_user(row) in (None, "") or owners_agree(_owner_user(row), anchor["user_id"])))
