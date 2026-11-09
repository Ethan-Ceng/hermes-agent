"""Publish a fork with its independent route, policy and exact message columns."""

import uuid

from sqlalchemy import func, select

from hermes_db.domains.sessions.postgres.operations import compression_publish, mutation_policy, retirement_guards, titles
from hermes_db.domains.sessions.postgres.queries import compression, gateway, messages as transcript, sessions
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.tables.conversations import messages, sessions as table
from hermes_db.core.values import decode_text
from hermes_state_local import POLICY_PREFIX
from hermes_state_mutation_branch import _child_policy
from hermes_state_runtime import RuntimeStoreError, _json


def boundary(conn, scope, target, through):
    if through is None:
        return conn.scalar(select(func.coalesce(func.max(messages.c.id), 0)).where(
            transcript.where(scope, [target]), messages.c.active == 1))
    row = transcript.one(conn, scope, target, through)
    if row is None or not row["active"]:
        raise RuntimeStoreError("invalid_params")
    if row["role"] == "assistant":
        for later in transcript.select_rows(conn, scope, [target], messages.c.active == 1, messages.c.id > through):
            if later["role"] != "tool":
                break
            through = later["id"]
    return through


def _title(conn, scope, parent):
    import re
    from hermes_state_titles import _NUMBERED_TITLE_RE

    base = decode_text(parent["title"]) or "branch"
    match = _NUMBERED_TITLE_RE.match(base)
    base = match.group(1) if match else base
    rows = conn.execute(select(table.c.title).where(table.c.store_id == scope.require_store_id(),
        (table.c.title == base.encode("utf-8")) | table.c.title_search.startswith(base + " #", autoescape=True))).scalars().all()
    if not rows:
        return base
    numbers = [int(value.rsplit(" #", 1)[1]) for raw in rows if re.fullmatch(re.escape(base) + r" #\d+", value := decode_text(raw))]
    return f"{base} #{max([1, *numbers]) + 1}"


def branch(conn, scope, session_id, payload, prepared):
    from gateway.config import Platform
    from gateway.session import SessionEntry, SessionSource, build_session_key
    from gateway.session_lifecycle import _now
    from hermes_state_keys import local_identity, profile_from_session_key
    from hermes_state_messages import _tool_calls_len

    snapshot = mutation_policy.local_snapshot(conn, scope, session_id)
    if prepared is not None and "snapshot" in prepared and prepared["snapshot"] != snapshot:
        raise RuntimeStoreError("revision_conflict")
    saved, target = snapshot["receipt"], snapshot["target"]
    retirement_guards.require_unleased(conn, scope, sorted({session_id, target}))
    through = boundary(conn, scope, target, payload.get("through_message_id"))
    request = prepared["request_id"] if prepared else "branch:" + uuid.uuid4().hex
    child = local_identity(saved["profile_id"], saved["principal_id"], request)
    policy = _child_policy(saved["policy"], child, prepared)
    source = SessionSource(Platform.LOCAL, child, user_id=saved["principal_id"], chat_type="dm", profile=saved["entry"]["origin"].get("profile"))
    route = build_session_key(source, profile=profile_from_session_key(saved["route"]))
    now = _now()
    entry = SessionEntry(route, child, now, now, origin=source, platform=Platform.LOCAL)
    parent = sessions.raw_session(conn, scope, target)
    if sessions.raw_session(conn, scope, child) is not None:
        raise RuntimeStoreError("admission_conflict")
    compression_publish.create_child(conn, scope, parent, child_session_id=child, source=policy["source"], model=policy["model"],
        config={"_branched_from": target}, cwd=policy["cwd"], profile_name=parent["profile_name"])
    rows = transcript.select_rows(conn, scope, [target], messages.c.active == 1, messages.c.id <= through)
    compression.clone_rows(conn, scope, target, [row["id"] for row in rows], target_session=child)
    sessions.update_session(conn, scope, child, {"session_key": route, "chat_id": child, "origin_json": _json(source.to_dict()),
        "system_prompt_hash": parent["system_prompt_hash"], "message_count": len(rows),
        "tool_call_count": sum(_tool_calls_len(row["tool_calls"]) for row in rows)})
    transcript.reconcile_orders(conn, scope, child)
    if rows:
        transcript.bump_revision(conn, scope, child)
    title = payload.get("title") or _title(conn, scope, parent)
    titles.set_title_on_connection(conn, scope, child, title, "user" if payload.get("title") else "derived")
    receipt = dict(profile_id=saved["profile_id"], principal_id=saved["principal_id"], request_id=request, session_id=child,
        route=route, entry=entry.to_dict(), policy=policy, picks=sorted(mutation_policy.picks(conn, scope, session_id)))
    if not gateway.save_route(conn, scope, "", route, _json(entry.to_dict()), now.timestamp()):
        raise RuntimeStoreError("admission_conflict")
    runtime.set_meta(conn, scope, POLICY_PREFIX + child, _json(receipt))
    return {session_id}, {"branched_session_id": child, "copied_messages": len(rows)}
