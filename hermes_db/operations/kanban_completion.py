"""Complete a captured run atomically; prepare and compensate its own files outside SQL."""

from pathlib import Path
import time

from hermes_db.errors import UnknownCommitError
from hermes_db.operations import kanban_completion_acceptance as acceptance
from hermes_db.operations.kanban_completion_guards import verify_on_connection
from hermes_db.operations.kanban_artifacts import insert_attachment
from hermes_db.operations.kanban_graph import _unsatisfied, recompute_ready
from hermes_db.repositories import kanban as repo, kanban_runs as run_repo

SNAPSHOT_FIELDS = ("status", "current_run_id", "claim_lock", "worker_pid", "worker_started_at", "workspace_kind",
                   "workspace_path", "completion_contract", "assignee")


def _matches(task, captured):
    return task is not None and all(task[field] == captured[field] for field in SNAPSHOT_FIELDS)


def _prepare_files(store, task_id, metadata):
    from hermes_cli import kanban_db as kb
    if not isinstance(metadata, dict):
        return [], []
    kb._persist_scratch_completion_artifacts(store, task_id, metadata)
    staged = [Path(value) for value in metadata.pop("_staged_artifacts", [])]
    try:
        from hermes_db.repositories.kanban_workspaces import canonical_path
        rows = [dict(filename=path.name, stored_path=str(path), size=path.stat().st_size, file_key=canonical_path(path)) for path in staged]
    except Exception:
        if staged:
            kb._discard_staged_copies(staged, staged[0].parent)
        raise
    return staged, rows


def _close_completed(conn, store, task, result, summary, metadata):
    from hermes_cli import kanban_db as kb
    handoff = summary if summary is not None else result
    run_id = run_repo.close_run(conn, store, task, outcome="completed", status="done", summary=handoff, metadata=metadata)
    if run_id is None and (summary or metadata is not None or result or task["status"] == "review"):
        if task["status"] == "review" and not handoff and not metadata:
            handoff = kb._REVIEW_APPROVED_NOTE
            metadata = {"source_status": "review", "approval": "manual"}
        run_id = run_repo.synthesize(conn, store, task, outcome="completed", summary=handoff, metadata=metadata)
    return run_id, handoff


def _write_completion(conn, store, captured, expected_run_id, result, summary, metadata, verified, prepared, rows):
    from hermes_cli import kanban_db as kb
    task_id = captured["id"]
    task = repo.get(conn, store, task_id)
    if not _matches(task, captured) or _unsatisfied(conn, store, task_id):
        return None
    if expected_run_id is not None and task["current_run_id"] != int(expected_run_id):
        return None
    if verify_on_connection(conn, store, task_id, verified)[1] or not acceptance.record(conn, store, task, prepared):
        return None
    repo.task_update(conn, store, task_id, status="done", result=result, completed_at=int(time.time()),
        claim_lock=None, claim_expires=None, worker_pid=None, block_kind=None, block_recurrences=0,
        consecutive_failures=0, last_failure_error=None)
    for row in rows:
        insert_attachment(conn, store, task_id, **row, uploaded_by="kanban_complete")
    run_id, handoff = _close_completed(conn, store, task, result, summary, metadata)
    event_summary = handoff or (kb._REVIEW_APPROVED_NOTE if task["status"] == "review" else None)
    repo.event(conn, store, task_id, "completed", kb._completed_event_payload(result, event_summary, verified, metadata), run_id)
    store.command_result(conn, True)
    return run_id, handoff


def _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force):
    from hermes_cli import kanban_db as kb
    with store.read() as conn:
        task = repo.get(conn, store, task_id)
        if _unsatisfied(conn, store, task_id):
            return None
    cards = tuple(created_cards or ())
    verified = kb._gate_created_cards(store, task_id, cards, summary or result)
    kb._gate_empty_completion(store, task_id, result=result, summary=summary)
    if task is None or task["status"] not in {"running", "ready", "blocked", "review"}:
        return None
    if expected_run_id is not None and task["current_run_id"] != int(expected_run_id):
        return None
    if expected_run_id is None and not force and kb._claim_is_live(task):
        raise kb.LiveClaimError(task_id)
    prepared = acceptance.prepare(store, task, expected_run_id, metadata)
    if prepared is False:
        return None
    if prepared is not None and not prepared[1]["ok"]:
        with store.write() as conn:
            current = repo.get(conn, store, task_id)
            if _matches(current, task):
                acceptance.record(conn, store, current, prepared)
        return None
    metadata = kb._merge_completion_prose_artifacts(store, task_id, metadata, summary=summary, result=result)
    metadata = dict(metadata) if isinstance(metadata, dict) else metadata
    return task, verified, metadata, prepared


def complete_task(store, task_id, *, result=None, summary=None, metadata=None, created_cards=None,
                  expected_run_id=None, fire_lifecycle_hook=True, force=False):
    from hermes_cli import kanban_db as kb
    preparation = _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force)
    if preparation is None:
        return False
    task, verified, metadata, prepared = preparation
    staged, rows = _prepare_files(store, task_id, metadata)
    durable = False
    try:
        with store.write() as conn:
            completed = _write_completion(conn, store, task, expected_run_id, result, summary, metadata, verified, prepared, rows)
        durable = completed is not None
    except UnknownCommitError:
        # COMMIT may have published the attachment rows; retain their content for reconciliation.
        durable = True
        raise
    finally:
        if staged and not durable:
            kb._discard_staged_copies(staged, staged[0].parent)
    if completed is None:
        return False
    run_id, handoff = completed
    kb._flag_phantom_prose_refs(store, task_id, run_id, summary, result, verified)
    recompute_ready(store)
    kb._cleanup_workspace(store, task_id)
    if fire_lifecycle_hook:
        kb._fire_task_hook("kanban_task_completed", kb.get_task(store, task_id), task_id, run_id, summary=handoff)
    return True
