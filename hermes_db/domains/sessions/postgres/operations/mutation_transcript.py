"""Canonical target advances and rewind on the current Local physical target."""

import time
import uuid

from hermes_db.domains.sessions.postgres.support.message_codec import codec
from hermes_db.domains.sessions.postgres.operations import compression, compression_publish, messages as writes, mutation_policy, retirement_guards
from hermes_db.domains.sessions.postgres.queries import lineage, messages, retirement, sessions
from hermes_db.repositories import worker_retirement
from hermes_db.tables.conversations import sessions as table
from hermes_state_mutations import COMPACTED_TARGET_DETAIL
from hermes_state_runtime import RuntimeStoreError


def compress(conn, scope, session_id, payload, prepared):
    snapshot = mutation_policy.validate_prepared(conn, scope, session_id, prepared)
    target, policy = snapshot["target"], snapshot["receipt"]["policy"]
    if prepared["in_place"]:
        child = target
        compression.compact_on_connection(conn, scope, target, prepared["messages"])
        affected = {session_id, target}
    else:
        child = uuid.uuid4().hex
        compression_publish.publish_on_connection(conn, scope, parent_session_id=target, child_session_id=child,
            source=policy["source"], model=policy["model"], messages=prepared["messages"],
            model_config={"_compressed_from": target}, cwd=policy["cwd"], require_compression_lease=False)
        affected = set()
    sessions.update_session(conn, scope, session_id, {"runtime_generation": table.c.runtime_generation + 1})
    return affected, {"target_session_id": child, "previous_target_session_id": target,
        "execution_generation": sessions.raw_session(conn, scope, session_id)["runtime_generation"],
        "message_count": len(prepared["messages"]), "summary": prepared.get("summary")}


def reset(conn, scope, session_id, payload):
    from gateway.session import SessionEntry
    from gateway.session_lifecycle import _now
    from hermes_state_local import POLICY_PREFIX
    from hermes_db.repositories import runtime
    import json

    raw = runtime.meta(conn, scope, POLICY_PREFIX + session_id)
    if raw is None:
        raise RuntimeStoreError("runtime_coordination_required")
    receipt = json.loads(raw)
    target = lineage.validate_local_receipt(conn, scope, receipt, session_id)
    targets = lineage.runtime_targets(conn, scope, session_id)
    retirement_guards.lock_targets(conn, scope, targets)
    worker_retirement.discard_orphans_on_reset(conn, scope, targets)
    retirement_guards.require_unleased(conn, scope, sorted({session_id, target}), allow_queued=True)
    parent = sessions.raw_session(conn, scope, target)
    policy, previous = receipt["policy"], SessionEntry.from_dict(receipt["entry"])
    now, child = _now(), uuid.uuid4().hex
    entry = SessionEntry(previous.session_key, child, now, now, origin=previous.origin, platform=previous.platform,
        chat_type=previous.chat_type, display_name=previous.display_name, is_fresh_reset=True)
    compression_publish.create_child(conn, scope, parent, child_session_id=child, source=policy["source"], model=policy["model"],
        config={"_reset_from": target}, cwd=policy["cwd"], profile_name=parent["profile_name"])
    sessions.update_session(conn, scope, target, {"ended_at": time.time(), "end_reason": "session_reset"})
    sessions.bump_generation(conn, scope, parent, "session_reset")
    lineage.advance_local_target(conn, scope, target, child, entry=entry.to_dict())
    sessions.update_session(conn, scope, session_id, {"runtime_generation": table.c.runtime_generation + 1})
    return set(), {"target_session_id": child, "previous_target_session_id": target,
        "execution_generation": sessions.raw_session(conn, scope, session_id)["runtime_generation"]}


def _summarized(conn, scope, physical, message_id):
    from sqlalchemy import select
    from hermes_db.tables.conversations import messages as rows

    row = conn.execute(select(rows.c.session_id, rows.c.role, rows.c.active, rows.c.compacted).where(
        rows.c.store_id == scope.require_store_id(), rows.c.id == message_id)).mappings().one_or_none()
    if row is None or row["role"] != "user":
        return False
    if row["session_id"] == physical:
        return row["active"] == 0 and row["compacted"] == 1
    return bool(row["active"] or row["compacted"]) and row["session_id"] in retirement.compression_members(conn, scope, [physical])


def rewind(conn, scope, session_id, payload):
    from agent.context_compressor import split_user_originated_turn
    from agent.message_metadata import typed_prompt_content

    physical = lineage.physical_target(conn, scope, session_id)
    targets = sorted({session_id, physical})
    retirement_guards.lock_targets(conn, scope, targets)
    retirement_guards.require_unleased(conn, scope, targets)
    target_id = payload["target_message_id"]
    row = messages.one(conn, scope, physical, target_id)
    if row is None or not row["active"] or row["role"] != "user":
        detail = COMPACTED_TARGET_DETAIL if _summarized(conn, scope, physical, target_id) else "target user message is no longer in session history"
        raise RuntimeStoreError("invalid_params", field="target_message_id", detail=detail)
    public = codec._row_to_message_dict(row, warn_context="rewind target", summary_flag=True)
    handoff, live = split_user_originated_turn(public)
    result = writes.rewind(conn, scope, physical, target_id,
        preserve_compaction_handoff=handoff is not None or payload.get("preserve_compaction_handoff", False))
    target = codec._row_to_message_dict(row, warn_context="rewind receipt", summary_flag=True)
    if handoff is not None:
        target["content"] = live.get("content")
    target["content"] = typed_prompt_content(target.get("content"), target)
    sessions.update_session(conn, scope, session_id, {"runtime_generation": table.c.runtime_generation + 1})
    return set(targets), {"rewound_count": result["rewound_count"], "target_message": target,
        "new_head_id": result["new_head_id"], "replacement_message_id": result.get("replacement_message_id")}
