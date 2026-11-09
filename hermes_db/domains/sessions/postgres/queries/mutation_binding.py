"""Existing control ownership over current rows, scoped to the selected store."""

import json

from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.domains.sessions.postgres.queries import sessions
from hermes_db.domains.runtime.receipts import BINDING_PREFIX
from hermes_db.domains.runtime.values import RuntimeStoreError


def history_binding(conn, scope, session_id):
    return runtime.meta(conn, scope, BINDING_PREFIX + session_id)


def binding_names(saved, scope, subject, *, ownership):
    try:
        value = json.loads(saved)
    except (TypeError, ValueError):
        return False
    if not isinstance(value, list) or len(value) != 2:
        return False
    namespace, owner = value
    return namespace == "store:" + scope.require_store_id() and ownership.same_owner(owner, subject)


def _binding(scope, actor):
    return json.dumps(["store:" + scope.require_store_id(), actor.subject], ensure_ascii=True, separators=(",", ":"))


def bindings_agree(first, second, scope, *, ownership):
    if first is None or second is None:
        return first is None and second is None
    try:
        values = [json.loads(saved) for saved in (first, second)]
    except (TypeError, ValueError):
        return False
    expected = "store:" + scope.require_store_id()
    if not all(isinstance(value, list) and len(value) == 2 and value[0] == expected
               and isinstance(value[1], str) and value[1] for value in values):
        return False
    return ownership.owners_agree(values[0][1], values[1][1])


def import_history_control(conn, scope, actor, session_ids):
    binding = _binding(scope, actor)
    for sid in session_ids:
        if sessions.raw_session(conn, scope, sid) is None:
            runtime.set_meta(conn, scope, BINDING_PREFIX + sid, binding)


def authorize_history(conn, scope, actor, session_id, *, ownership, claim=False):
    row = sessions.raw_session(conn, scope, session_id)
    if row is None or row["session_key"] or row["chat_id"] or row["origin_json"]:
        return False
    saved = history_binding(conn, scope, session_id)
    if saved is not None:
        if not binding_names(saved, scope, actor.subject, ownership=ownership):
            raise RuntimeStoreError("permission_denied")
        return True
    if not ownership.history_row(row):
        return False
    if ownership.owner_user(row) and not ownership.same_owner(row["user_id"], actor.subject):
        raise RuntimeStoreError("permission_denied")
    if "session:create" not in actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    if claim:
        runtime.set_meta(conn, scope, BINDING_PREFIX + session_id, _binding(scope, actor))
    return True


def same_history_owner(conn, scope, anchor_id, session_id, *, ownership):

    anchor, row = (sessions.raw_session(conn, scope, sid) for sid in (anchor_id, session_id))
    if anchor is None or row is None:
        return False
    if row["session_key"] or row["chat_id"] or row["origin_json"]:
        return tuple(row[name] for name in ("user_id", "session_key", "chat_id")) == tuple(
            anchor[name] for name in ("user_id", "session_key", "chat_id"))
    binding = runtime.meta(conn, scope, BINDING_PREFIX + session_id)
    if not bindings_agree(binding, runtime.meta(conn, scope, BINDING_PREFIX + anchor_id), scope, ownership=ownership):
        return False
    peer = row["source"] == anchor["source"] and not any(anchor[name] for name in ("session_key", "chat_id", "origin_json"))
    return binding is not None or ((ownership.history_row(row) or peer)
        and (ownership.owner_user(row) in (None, "") or ownership.owners_agree(ownership.owner_user(row), anchor["user_id"])))
