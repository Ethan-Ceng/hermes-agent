"""Complete a captured run atomically; prepare and compensate its own files outside SQL."""

from pathlib import Path
import time

from hermes_db.errors import UnknownCommitError
from hermes_db.domains.kanban.postgres.operations import completion_acceptance as acceptance
from hermes_db.domains.kanban.postgres.operations.completion_guards import verify_on_connection
from hermes_db.domains.kanban.postgres.operations.artifacts import insert_attachment
from hermes_db.domains.kanban.postgres.operations.graph import _unsatisfied
from hermes_db.domains.kanban.postgres.operations.effects import enqueue, hook_step, after_commit
from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo

SNAPSHOT_FIELDS = ("status", "current_run_id", "claim_lock", "worker_pid", "worker_started_at", "workspace_kind",
                   "workspace_path", "completion_contract", "assignee")


def _matches(task, captured):
    return task is not None and all(task[field] == captured[field] for field in SNAPSHOT_FIELDS)


def _prepare_files(store, task_id, metadata):
    from hermes_cli import kanban_db as kb
    if not isinstance(metadata, dict):
        return [], []
    from hermes_db.domains.kanban.postgres.operations.attachment_cleanup import prepare_directory
    directory = prepare_directory(store, kb.task_attachments_dir(task_id))
    try:
        kb._persist_scratch_completion_artifacts(store, task_id, metadata, attachment_dir=directory)
    except Exception:
        from hermes_db.domains.kanban.postgres.operations.attachment_cleanup import discard_empty_generation
        discard_empty_generation(store, directory)
        raise
    staged = [Path(value) for value in metadata.pop("_staged_artifacts", [])]
    try:
        from hermes_db.domains.kanban.postgres.queries.workspaces import canonical_path
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


def _write_completion(conn, store, captured, expected_run_id, result, summary, metadata, verified, prepared, rows, fire_lifecycle_hook):
    from hermes_cli import kanban_db as kb
    task_id = captured["id"]
    task = repo.get(conn, store, task_id)
    if not _matches(task, captured) or _unsatisfied(conn, store, task_id):
        store.command_result(conn, False)
        return None
    if expected_run_id is not None and task["current_run_id"] != int(expected_run_id):
        store.command_result(conn, False)
        return None
    if verify_on_connection(conn, store, task_id, verified)[1] or not acceptance.record(conn, store, task, prepared):
        store.command_result(conn, False)
        return None
    repo.task_update(conn, store, task_id, status="done", result=result, completed_at=int(time.time()),
        claim_lock=None, claim_expires=None, worker_pid=None, block_kind=None, block_recurrences=0,
        consecutive_failures=0, last_failure_error=None)
    for row in rows:
        insert_attachment(conn, store, task_id, **row, uploaded_by="kanban_complete")
    run_id, handoff = _close_completed(conn, store, task, result, summary, metadata)
    event_summary = handoff or (kb._REVIEW_APPROVED_NOTE if task["status"] == "review" else None)
    repo.event(conn, store, task_id, "completed", kb._completed_event_payload(result, event_summary, verified, metadata), run_id)
    steps = [dict(kind="phantom", task_id=task_id, run_id=run_id, summary=summary, result=result, verified=verified),
        dict(kind="ready"), dict(kind="workspace", task_id=task_id)]
    if fire_lifecycle_hook:
        steps.append(hook_step(store, task, "kanban_task_completed", run_id, summary=handoff))
    effect_id = enqueue(conn, store, steps)
    store.command_result(conn, True)
    return run_id, handoff, effect_id


def _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if _unsatisfied(conn, store, task_id):
            store.command_result(conn, False)
            return None
        if task is None or task["status"] not in {"running", "ready", "blocked", "review"}:
            store.command_result(conn, False)
            return None
        if expected_run_id is not None and task["current_run_id"] != int(expected_run_id):
            store.command_result(conn, False)
            return None
    cards = tuple(created_cards or ())
    verified = kb._gate_created_cards(store, task_id, cards, summary or result)
    kb._gate_empty_completion(store, task_id, result=result, summary=summary)
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
            store.command_result(conn, False)
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
    from hermes_db.domains.kanban.postgres.operations.file_jobs import local_files_lock
    with local_files_lock(store.scope.profile_home):
        staged, rows = _prepare_files(store, task_id, metadata)
        durable = False
        try:
            with store.write() as conn:
                completed = _write_completion(conn, store, task, expected_run_id, result, summary, metadata, verified, prepared, rows, fire_lifecycle_hook)
            durable = completed is not None
        except UnknownCommitError:
            # COMMIT may have published the attachment rows; retain their content for reconciliation.
            durable = True
            raise
        finally:
            if staged and not durable:
                from hermes_db.domains.kanban.postgres.operations.attachment_cleanup import discard_copies
                discard_copies(store, staged)
    if completed is None:
        return False
    after_commit(store, completed[2])
    return True
