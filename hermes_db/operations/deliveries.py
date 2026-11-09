"""Short delivery metadata transactions; external sends are always the caller's work."""

import time
import uuid

from gateway import delivery_ledger as policy
from hermes_db.delivery_claim import DeliveryClaim
from hermes_db.repositories import deliveries as repo, sessions
from hermes_db.tables.gateway import delivery_obligations as table
from hermes_db.core.values import encode_text
from hermes_state_runtime import RuntimeStoreError


def _proof(scope, row):
    return DeliveryClaim(scope.require_store_id(), row["obligation_id"], row["owner_instance_id"], row["claim_token"])


def _owner(instance, ttl, now, *, token=None):
    return {"owner_instance_id": instance, "claim_token": token or uuid.uuid4().hex, "claim_expires_at": now + ttl}


def record(conn, scope, instance, ttl, *, obligation_id, session_key, platform, chat_id, thread_id, content, adapter_profile=None):
    sessions.lock_store(conn, scope, exclusive=True)
    now = time.time()
    current = repo.record(conn, scope, dict(obligation_id=obligation_id, session_key=session_key, platform=platform,
        chat_id=str(chat_id), thread_id=str(thread_id) if thread_id else None, content=encode_text(content), state="pending",
        attempts=0, created_at=now, updated_at=now, adapter_profile=str(adapter_profile).strip() if adapter_profile else "default",
        **_owner(instance, ttl, now)))
    # Identity replays do not replace another claimant or reset spent attempts.
    identity = {"session_key": session_key, "content": content, "platform": platform, "chat_id": str(chat_id),
        "thread_id": str(thread_id) if thread_id else None, "adapter_profile": str(adapter_profile).strip() if adapter_profile else "default"}
    if any(current[name] != value for name, value in identity.items()):
        raise RuntimeStoreError("admission_conflict")
    proof = _proof(scope, current) if current["owner_instance_id"] == instance else None
    repo.prune(conn, scope, now, policy._RETENTION_SECONDS, policy._MAX_ROWS)
    return proof


def mark(conn, scope, instance, proof, state, ttl, error=""):
    if not isinstance(proof, DeliveryClaim) or proof.store_id != scope.require_store_id() or proof.instance_id != instance:
        return False
    sessions.lock_store(conn, scope, exclusive=True)
    now = time.time()
    return repo.update_owned(conn, scope, proof, {"state": state, "updated_at": now, "claim_expires_at": now + ttl,
        "last_error": encode_text(error[:500]) if error else None}, table.c.state.in_(("pending", "attempting", "failed")))


def record_crash_left(conn, scope, *, obligation_id, session_key, platform, chat_id, thread_id, content, since, adapter_profile=None):
    sessions.lock_store(conn, scope, exclusive=True)
    if repo.reply_recorded_since(conn, scope, session_key, encode_text(content), since):
        return
    now = time.time()
    repo.record(conn, scope, dict(obligation_id=obligation_id, session_key=session_key, platform=platform,
        chat_id=str(chat_id), thread_id=str(thread_id) if thread_id else None, content=encode_text(content),
        state="attempting", attempts=0, created_at=now, updated_at=now,
        adapter_profile=str(adapter_profile).strip() if adapter_profile else "default"))


def release(conn, scope, instance, proof, error):
    if not isinstance(proof, DeliveryClaim) or proof.store_id != scope.require_store_id() or proof.instance_id != instance:
        return False
    sessions.lock_store(conn, scope, exclusive=True)
    from sqlalchemy import case
    return repo.update_owned(conn, scope, proof, {"state": "failed", "updated_at": time.time(),
        "attempts": case((table.c.attempts > 0, table.c.attempts - 1), else_=0),
        "last_error": encode_text(error[:500]) if error else None}, table.c.state == "attempting")


def _budget(row, now):
    return row["attempts"] < policy.MAX_ATTEMPTS and now - row["created_at"] <= policy.STALE_AFTER_SECONDS


def _claimed(scope, row, proof, *, runtime=False, adopted=False, due=None):
    if adopted:
        return {key: row[key] for key in ("obligation_id", "session_key", "platform", "chat_id", "thread_id", "content", "attempts")} | {
            "profile": row["adapter_profile"], "adopted": True, "not_before": due, "_claim": proof}
    result = policy._claimed_row(*(row[key] for key in ("obligation_id", "session_key", "platform", "chat_id", "thread_id", "content", "attempts", "adapter_profile")),
        needs_marker=runtime or row["state"] != "pending" or row["attempts"] > 0,
        runtime=runtime, flood=row["state"] == "failed" and policy.is_flood_error(row["last_error"]), last_error=row["last_error"] if runtime else None)
    return dict(result, _claim=proof)


def sweep(conn, scope, instance, ttl, now, *, deliverable_platforms=None, deliverable_targets=None, platform=None, profile=None):
    sessions.lock_store(conn, scope, exclusive=True)
    runtime = platform is not None
    conditions = [table.c.owner_instance_id == instance, table.c.state == "failed", table.c.platform == platform] if runtime else [repo.available(instance, now)]
    rows, claimed = repo.unsettled(conn, scope, *conditions), []
    for row in rows:
        if runtime and row["adapter_profile"] != (profile or "default"):
            continue
        due = policy.retry_not_before(row["updated_at"], row["last_error"], row["attempts"]) if runtime else None
        if runtime and due is None:
            continue
        if not _budget(row, now):
            repo.claim(conn, scope, row["obligation_id"], {"state": "abandoned", "updated_at": now}, *conditions)
            continue
        if deliverable_platforms is not None and row["platform"] not in deliverable_platforms:
            continue
        if deliverable_targets is not None and (row["platform"], row["adapter_profile"]) not in deliverable_targets:
            continue
        flood = row["state"] == "failed" and policy.is_flood_error(row["last_error"])
        wait = policy.flood_not_before(row["updated_at"], row["last_error"]) if flood else None
        adopted = not runtime and wait is not None and now < wait
        if runtime and now < due:
            continue
        values = _owner(instance, ttl, now)
        if not adopted:
            values.update(state="attempting", attempts=table.c.attempts + 1, updated_at=now)
            if runtime or flood:
                values["last_error"] = None
        if repo.claim(conn, scope, row["obligation_id"], values, *conditions):
            proof = DeliveryClaim(scope.require_store_id(), row["obligation_id"], instance, values["claim_token"])
            claimed.append(_claimed(scope, row, proof, runtime=runtime, adopted=adopted, due=wait))
    return claimed


def pending(conn, scope, instance, now):
    earliest = {}
    for row in repo.unsettled(conn, scope, table.c.state == "failed", table.c.owner_instance_id == instance):
        if policy.is_reconnect_only(row["last_error"]) or not _budget(row, now):
            continue
        due = policy.retry_not_before(row["updated_at"], row["last_error"], row["attempts"])
        if due is not None:
            key = row["platform"], row["adapter_profile"]
            earliest[key] = min(earliest.get(key, due), due)
    return [{"platform": platform, "profile": profile, "not_before": due} for (platform, profile), due in sorted(earliest.items())]
