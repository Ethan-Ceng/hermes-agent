"""Shared retry cooldown and duplicate-work policy, independent of SQL dialect."""
from hermes_db.domains.kanban import rules as _storage_shared_1


def primary_guard(error, latest, lane, now):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    cooldown = kb._resolve_rate_limit_cooldown_seconds()
    outcome = latest["outcome"] if latest is not None else None
    ended = kb._to_epoch(latest["ended_at"]) if latest is not None else None
    recent = cooldown > 0 and ended is not None and now - ended < cooldown
    if outcome == "spawn_failed" and recent and _storage_shared_1._json_dict(latest["metadata"]).get("infrastructure"):
        return True, "infrastructure_cooldown"
    if outcome == "rate_limited":
        return True, "rate_limit_cooldown" if recent else None
    error = kb._lossy_text(error)
    if error and outcome != "crashed" and dispatch._RESPAWN_BLOCKER_RE.search(error):
        return True, "blocker_auth"
    return lane == "review", None


def history_guard(successes, events, comments):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    success = max((t for t, _ in successes), default=None)
    requeues = {"status", "promoted", "unblocked", "reclaimed"}
    if success is not None and not any(t >= success and event["kind"] in requeues for t, event in events):
        return "recent_success"
    pr_times = [t for t, comment in comments if dispatch._RESPAWN_GUARD_PR_URL_RE.search(kb._lossy_text(comment["body"]) or "")]
    if not pr_times:
        return None
    latest_pr = max(pr_times)
    handoffs = {"assigned", "changes_requested", "review_reopened"}
    if any(t > latest_pr and event["kind"] in handoffs and dispatch._is_handoff_event(event["kind"], event["payload"])
           for t, event in events):
        return None
    return "active_pr"
