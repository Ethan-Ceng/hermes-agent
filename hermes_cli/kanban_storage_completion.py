"""Kanban completion preparation, files and post-commit application workflow."""
from pathlib import Path
from hermes_db.domains.kanban import rules as _storage_shared_1_, rules as _storage_shared_1
from hermes_db.errors import UnknownCommitError
from hermes_cli.kanban_storage_effects import after_commit

def _prepare_files(store, task_id, metadata):

    if not isinstance(metadata, dict):
        return ([], [])
    from hermes_cli.kanban_storage_files import prepare_directory
    directory = prepare_directory(store, store.files.task_attachments_dir(task_id))
    try:
        store.files.persist_scratch_completion_artifacts(store, task_id, metadata, attachment_dir=directory)
    except Exception:
        from hermes_cli.kanban_storage_files import discard_empty_generation
        discard_empty_generation(store, directory)
        raise
    staged = [Path(value) for value in metadata.pop('_staged_artifacts', [])]
    try:
        from hermes_cli.kanban_storage_owner import canonical_path
        rows = [dict(filename=path.name, stored_path=str(path), size=path.stat().st_size, file_key=canonical_path(path)) for path in staged]
    except Exception:
        if staged:
            store.files.discard_staged_copies(staged, staged[0].parent)
        raise
    return (staged, rows)

def _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force):
    from hermes_db.domains.kanban.postgres import completion as db

    task = db.capture_completion(store, task_id, expected_run_id)
    if task is None:
        return None
    cards = tuple(created_cards or ())
    verified = store._gate_created_cards(task_id, cards, summary or result)
    store._gate_empty_completion(task_id, result=result, summary=summary)
    if expected_run_id is None and (not force) and store.processes.claim_is_live(task):
        raise store.result_values.live_claim_error(task_id)
    prepared = prepare(store, task, expected_run_id, metadata)
    if prepared is False:
        return None
    if prepared is not None and (not prepared[1]['ok']):
        db.record_failed_acceptance(store, task_id, task, prepared)
        return None
    metadata = store.files.merge_completion_prose_artifacts(store, task_id, metadata, summary=summary, result=result)
    metadata = dict(metadata) if isinstance(metadata, dict) else metadata
    return (task, verified, metadata, prepared)

def complete_task(store, task_id, *, result=None, summary=None, metadata=None, created_cards=None, expected_run_id=None, fire_lifecycle_hook=True, force=False):
    from hermes_db.domains.kanban.postgres import completion as db

    preparation = _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force)
    if preparation is None:
        return False
    task, verified, metadata, prepared = preparation
    from hermes_cli.kanban_storage_files import local_files_lock
    with local_files_lock(store.scope.profile_home):
        staged, rows = _prepare_files(store, task_id, metadata)
        durable = False
        try:
            with store.write() as conn:
                completed = db._write_completion(conn, store, task, expected_run_id, result, summary, metadata, verified, prepared, rows, fire_lifecycle_hook)
            durable = completed is not None
        except UnknownCommitError:
            durable = True
            raise
        finally:
            if staged and (not durable):
                from hermes_cli.kanban_storage_files import discard_copies
                discard_copies(store, staged)
    if completed is None:
        return False
    after_commit(store, completed[2])
    return True

def prepare(store, task, expected_run_id, metadata):
    from hermes_db.domains.kanban.postgres import completion as db

    contract = task['completion_contract']
    if not contract or contract == 'local-only':
        return None
    if expected_run_id is not None and task['current_run_id'] != expected_run_id:
        return False
    published_pr = metadata.get('published_pr') if isinstance(metadata, dict) else None
    match = _storage_shared_1_._PR.fullmatch(published_pr) if isinstance(published_pr, str) else None
    captured = db.snapshot(task)
    if match and contract == match[1]:
        if not db.publish_completion_contract(store, task, captured, published_pr):
            return False
        task['completion_contract'] = contract = published_pr
        captured = db.snapshot(task)
    receipt = store.files.collect_acceptance(contract, published_pr, assignee=task['assignee'])
    return (captured, receipt)


def edit_result(store, task_id, *, title, body, priority, result, summary, metadata, board):
    from hermes_db.domains.kanban.postgres import completion as db
    from hermes_cli.kanban_storage_catalog import notify_task_updated
    written, changed = db.write_completed_result(store, task_id, title=title, body=body,
        priority=priority, result=result, summary=summary, metadata=metadata, board=board)
    if written:
        notify_task_updated(store, task_id, changed, board=board)
    return written
