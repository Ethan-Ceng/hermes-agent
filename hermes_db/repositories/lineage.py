"""Current local receipt and compression scope used by execution exclusion."""

import json
from itertools import pairwise

from sqlalchemy import select

from hermes_db.repositories import sessions
from hermes_db.tables.conversations import sessions as session_table
from hermes_db.values import model_config
from hermes_db.values import preferred_children
from hermes_state_local import POLICY_PREFIX
from hermes_state_runtime import RuntimeStoreError


def physical_target(conn, scope, session_id):
    from hermes_db.repositories.runtime import meta
    raw = meta(conn, scope, POLICY_PREFIX + session_id)
    if raw is None:
        return session_id
    try:
        receipt = json.loads(raw)
        return validate_local_receipt(conn, scope, receipt, session_id)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, RuntimeStoreError):
            raise
        raise RuntimeStoreError("storage_unavailable") from None


def validate_local_receipt(conn, scope, receipt, session_id):
    from hermes_state_keys import local_identity

    if receipt["session_id"] != session_id or session_id != local_identity(
            receipt["profile_id"], receipt["principal_id"], receipt["request_id"]):
        raise RuntimeStoreError("storage_unavailable")
    lineage = receipt.get("lineage", [session_id])
    if not isinstance(lineage, list) or not lineage or len(set(lineage)) != len(lineage) or lineage[0] != session_id or lineage[-1] != receipt["entry"]["session_id"]:
        raise RuntimeStoreError("storage_unavailable")
    rows = sessions.get_sessions(conn, scope, lineage)
    for parent_id, child_id in pairwise(lineage):
        parent, child = rows.get(parent_id), rows.get(child_id)
        if not parent or not child or child["parent_session_id"] != parent_id:
            raise RuntimeStoreError("storage_unavailable")
        if parent["end_reason"] == "session_reset":
            valid = model_config(child["model_config"]).get("_reset_from") == parent_id
        else:
            valid = parent["end_reason"] == "compression" and preferred_children(
                sessions.lineage_rows(conn, scope, parent_id)).get(parent_id) == child_id
        if not valid:
            raise RuntimeStoreError("storage_unavailable")
    if sessions.raw_session(conn, scope, lineage[-1]) is None or sessions.compression_tip(conn, scope, lineage[-1]) != lineage[-1]:
        raise RuntimeStoreError("storage_unavailable")
    return lineage[-1]


def runtime_targets(conn, scope, session_id):
    from hermes_db.repositories.runtime import meta
    targets = {session_id, physical_target(conn, scope, session_id)}
    current = sessions.raw_session(conn, scope, session_id)
    if current and current["chat_id"]:
        raw = meta(conn, scope, POLICY_PREFIX + current["chat_id"])
        if raw is not None:
            receipt = json.loads(raw)
            if session_id in receipt.get("lineage", [current["chat_id"]]):
                targets.update((current["chat_id"], physical_target(conn, scope, current["chat_id"])))
    roots = select(session_table.c.lineage_root_id).where(session_table.c.store_id == scope.require_store_id(), session_table.c.id.in_(targets))
    targets.update(conn.execute(select(session_table.c.id).where(session_table.c.store_id == scope.require_store_id(),
        session_table.c.lineage_root_id.in_(roots))).scalars())
    return targets
