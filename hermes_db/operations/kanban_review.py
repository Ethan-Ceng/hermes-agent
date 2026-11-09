"""Review handoffs keep their implementer/reviewer and exact run ownership."""

import time
from sqlalchemy import select

from hermes_db.errors import UnknownCommitError
from hermes_db.operations.kanban_claims import _close_dangling
from hermes_db.operations.kanban_completion import _matches, _prepare_files
from hermes_db.operations.kanban_artifacts import insert_attachment
from hermes_db.operations.kanban_graph import _unsatisfied
from hermes_db.repositories import kanban as repo, kanban_runs as run_repo
from hermes_db.tables.kanban import runs, events
from hermes_db.core.values import decode_text


def _latest(conn, store, task_id, kind, run_id=None):
    query = select(events.c.payload).where(repo.key(store, task_id, events), events.c.kind == kind.encode())
    if run_id is not None:
        query = query.where(events.c.run_id == run_id)
    row = conn.execute(query.order_by(events.c.id.desc()).limit(1)).one_or_none()
    if row is None:
        return None
    from hermes_cli.kanban_db import _json_dict
    return _json_dict(decode_text(row[0]))


def _prior_reviewer(conn, store, task_id):
    run_id = conn.scalar(select(runs.c.id).where(repo.key(store, task_id, runs),
        runs.c.outcome == b"changes_requested").order_by(runs.c.id.desc()).limit(1))
    if run_id is None:
        return None
    reviewer = (_latest(conn, store, task_id, "changes_requested", run_id) or {}).get("reviewer")
    return reviewer if isinstance(reviewer, str) and reviewer.strip() else False


def _prepare_review(store, task_id, reviewer, expected_run_id, force):
    from hermes_cli import kanban_db as kb
    with store.read() as conn:
        if _unsatisfied(conn, store, task_id):
            return "parent dependencies are not satisfied"
        task = repo.get(conn, store, task_id)
        if task is None:
            return "task not found"
        if reviewer is None:
            reviewer = _prior_reviewer(conn, store, task_id)
        if reviewer is False:
            return ("re-review has no durable reviewer provenance (the latest changes_requested event is missing or "
                    "malformed); pass reviewer= explicitly")
        reviewer = kb._canonical_assignee(reviewer)
        run = run_repo.get(conn, store, task["current_run_id"]) if task["current_run_id"] is not None else None
        implementer = run["profile"] if run is not None else None
        if implementer is None and task["assignee"] != reviewer:
            implementer = task["assignee"]
    if expected_run_id is None and not force and kb._claim_is_live(task):
        return ("task is running under a live claim; pass expected_run_id (worker ownership) or force=True "
                "(explicit operator override) instead of clearing the live run's claim")
    if task["status"] not in {"running", "ready"} or (expected_run_id is not None and task["current_run_id"] != int(expected_run_id)):
        return "task is not in running/ready (or expected_run_id did not match the current run)"
    return task, reviewer, implementer


def _write_review(conn, store, task, reviewer, implementer, summary, metadata, rows):
    from hermes_cli import kanban_db as kb
    task_id = task["id"]
    current = repo.get(conn, store, task_id)
    if not _matches(current, task) or _unsatisfied(conn, store, task_id):
        return False
    values = dict(status="review", claim_lock=None, claim_expires=None, worker_pid=None)
    if reviewer is not None:
        values["assignee"] = reviewer
    repo.task_update(conn, store, task_id, **values)
    for row in rows:
        insert_attachment(conn, store, task_id, **row, uploaded_by="kanban_request_review")
    run_id = run_repo.close_run(conn, store, task, outcome="review_requested", status="review", summary=summary, metadata=metadata)
    if run_id is None and (summary or metadata is not None):
        run_id = run_repo.synthesize(conn, store, task, outcome="review_requested", summary=summary, metadata=metadata, profile=implementer)
    payload = {"summary": kb._first_line(summary, 400) or None, "implementer": implementer, "reviewer": reviewer}
    artifacts = kb._cleaned_artifact_paths(metadata)
    if artifacts:
        payload["artifacts"] = artifacts
    repo.event(conn, store, task_id, "review_requested", payload, run_id)
    return True


def request_review(store, task_id, *, summary=None, metadata=None, reviewer=None, expected_run_id=None, force=False, with_reason=False):
    from hermes_cli import kanban_db as kb
    preparation = _prepare_review(store, task_id, reviewer, expected_run_id, force)
    if isinstance(preparation, str):
        return (False, preparation) if with_reason else False
    task, reviewer, implementer = preparation
    summary, metadata = kb.redact_review_value(summary), kb.redact_review_value(metadata)
    metadata = kb._merge_completion_prose_artifacts(store, task_id, metadata, summary=summary, result=None)
    metadata = dict(metadata) if isinstance(metadata, dict) else metadata
    from hermes_db.operations.kanban_file_jobs import local_files_lock
    with local_files_lock(store.scope.profile_home):
        staged, rows = _prepare_files(store, task_id, metadata)
        durable = False
        try:
            with store.write() as conn:
                completed = _write_review(conn, store, task, reviewer, implementer, summary, metadata, rows)
                reason = None if completed else "task changed during review handoff"
                store.command_result(conn, (completed, reason) if with_reason else completed)
            durable = completed
        except UnknownCommitError:
            durable = True
            raise
        finally:
            if staged and not durable:
                from hermes_db.operations.kanban_attachment_cleanup import discard_copies
                discard_copies(store, staged)
    reason = None if durable else "task changed during review handoff"
    return (durable, reason) if with_reason else durable


def request_changes(store, task_id, *, reason, expected_run_id=None):
    from hermes_cli import kanban_db as kb
    reason = str(kb.redact_review_value(reason or "")).strip()
    if not reason:
        return False, "reason is required"
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        error = _changes_error(task, expected_run_id)
        if error:
            return store.command_result(conn, (False, error))
        if run_repo.retry_status(conn, store, task_id, task["current_run_id"]) != "review":
            return store.command_result(conn, (False, "active run was not claimed from review"))
        requested = _latest(conn, store, task_id, "review_requested")
        if requested is None:
            return store.command_result(conn, (False, "no prior review_requested event"))
        implementer = kb._nonblank_str(requested.get("implementer"))
        if implementer is None:
            return store.command_result(conn, (False, "review handoff has no valid implementer provenance"))
        reviewer = kb._canonical_assignee(kb._nonblank_str(task["assignee"]))
        status = "todo" if _unsatisfied(conn, store, task_id) else "ready"
        repo.task_update(conn, store, task_id, status=status, assignee=implementer, claim_lock=None,
            claim_expires=None, worker_pid=None, worker_started_at=None)
        run_id = run_repo.close_run(conn, store, task, outcome="changes_requested", status=status, summary=reason)
        repo.event(conn, store, task_id, "changes_requested", {"reason": reason,
            "implementer": implementer, "reviewer": reviewer, "status": status}, run_id)
        store.command_result(conn, (True, implementer))
    return True, implementer


def _changes_error(task, expected_run_id):
    if task is None:
        return "task not found"
    if task["status"] != "running" or task["current_run_id"] is None:
        return "task is not in an active review run"
    if expected_run_id is not None and task["current_run_id"] != int(expected_run_id):
        return "run_id mismatch"
    return None


def reopen_review_task(store, task_id):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task["status"] != "review":
            return False
        _close_dangling(conn, store, task, int(time.time()), "invariant recovery on review reopen")
        status = "todo" if _unsatisfied(conn, store, task_id) else "ready"
        implementer = kb._nonblank_str((_latest(conn, store, task_id, "review_requested") or {}).get("implementer"))
        values = dict(status=status, current_run_id=None, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
        payload = {"status": status}
        if implementer:
            values["assignee"] = payload["implementer"] = implementer
        repo.task_update(conn, store, task_id, **values)
        repo.event(conn, store, task_id, "review_reopened", payload if payload != {"status": "ready"} else None)
        store.command_result(conn, True)
    return True
