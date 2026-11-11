"""Application-owned review preparation and original artifact publication fences."""
from hermes_db.domains.kanban import rules as _storage_shared_1_, rules as _storage_shared_1
from hermes_db.errors import UnknownCommitError
from hermes_cli.kanban_storage_completion import _prepare_files

def _prepare_review(store, task_id, reviewer, expected_run_id, force):
    from hermes_db.domains.kanban.postgres import review as db

    preparation = db.capture_review(store, task_id, reviewer)
    if isinstance(preparation, str):
        return preparation
    task, reviewer, implementer = preparation
    if expected_run_id is None and (not force) and store.processes.claim_is_live(task):
        return "task is running under a live claim; pass expected_run_id (worker ownership) or force=True (explicit operator override) instead of clearing the live run's claim"
    if task['status'] not in {'running', 'ready'} or (expected_run_id is not None and task['current_run_id'] != int(expected_run_id)):
        return 'task is not in running/ready (or expected_run_id did not match the current run)'
    return (task, reviewer, implementer)

def request_review(store, task_id, *, summary=None, metadata=None, reviewer=None, expected_run_id=None, force=False, with_reason=False):
    from hermes_db.domains.kanban.postgres import review as db

    preparation = _prepare_review(store, task_id, reviewer, expected_run_id, force)
    if isinstance(preparation, str):
        return (False, preparation) if with_reason else False
    task, reviewer, implementer = preparation
    summary, metadata = (_storage_shared_1_.redact_review_value(summary), _storage_shared_1_.redact_review_value(metadata))
    metadata = store.files.merge_completion_prose_artifacts(store, task_id, metadata, summary=summary, result=None)
    metadata = dict(metadata) if isinstance(metadata, dict) else metadata
    from hermes_cli.kanban_storage_files import local_files_lock
    with local_files_lock(store.scope.profile_home):
        staged, rows = _prepare_files(store, task_id, metadata)
        durable = False
        try:
            with store.write() as conn:
                completed = db._write_review(conn, store, task, reviewer, implementer, summary, metadata, rows)
                reason = None if completed else 'task changed during review handoff'
                store.command_result(conn, (completed, reason) if with_reason else completed)
            durable = completed
        except UnknownCommitError:
            durable = True
            raise
        finally:
            if staged and (not durable):
                from hermes_cli.kanban_storage_files import discard_copies
                discard_copies(store, staged)
    reason = None if durable else 'task changed during review handoff'
    return (durable, reason) if with_reason else durable
