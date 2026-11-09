"""Kanban completion workflow; original connection, fence and off-connection effect boundaries are preserved."""
from pathlib import Path
import time
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.kanban.postgres.files import insert_attachment
from hermes_db.domains.kanban.postgres.catalog import _unsatisfied
from hermes_db.domains.kanban.postgres.effects import enqueue, hook_step, after_commit
from hermes_db.domains.kanban.postgres import repository as repo, runs as run_repo
from sqlalchemy import select, func
from hermes_db.tables.kanban import tasks, runs
from hermes_db.core.values import decode_text, encode_text
import json
SNAPSHOT_FIELDS = ('status', 'current_run_id', 'claim_lock', 'worker_pid', 'worker_started_at', 'workspace_kind', 'workspace_path', 'completion_contract', 'assignee')

def _matches(task, captured):
    return task is not None and all(task[field] == captured[field] for field in SNAPSHOT_FIELDS)

def _prepare_files(store, task_id, metadata):
    from hermes_cli import kanban_db as kb
    if not isinstance(metadata, dict):
        return ([], [])
    from hermes_db.domains.kanban.postgres.files import prepare_directory
    directory = prepare_directory(store, kb.task_attachments_dir(task_id))
    try:
        kb._persist_scratch_completion_artifacts(store, task_id, metadata, attachment_dir=directory)
    except Exception:
        from hermes_db.domains.kanban.postgres.files import discard_empty_generation
        discard_empty_generation(store, directory)
        raise
    staged = [Path(value) for value in metadata.pop('_staged_artifacts', [])]
    try:
        from hermes_db.domains.kanban.postgres.workspaces import canonical_path
        rows = [dict(filename=path.name, stored_path=str(path), size=path.stat().st_size, file_key=canonical_path(path)) for path in staged]
    except Exception:
        if staged:
            kb._discard_staged_copies(staged, staged[0].parent)
        raise
    return (staged, rows)

def _close_completed(conn, store, task, result, summary, metadata):
    from hermes_cli import kanban_db as kb
    handoff = summary if summary is not None else result
    run_id = run_repo.close_run(conn, store, task, outcome='completed', status='done', summary=handoff, metadata=metadata)
    if run_id is None and (summary or metadata is not None or result or (task['status'] == 'review')):
        if task['status'] == 'review' and (not handoff) and (not metadata):
            handoff = kb._REVIEW_APPROVED_NOTE
            metadata = {'source_status': 'review', 'approval': 'manual'}
        run_id = run_repo.synthesize(conn, store, task, outcome='completed', summary=handoff, metadata=metadata)
    return (run_id, handoff)

def _write_completion(conn, store, captured, expected_run_id, result, summary, metadata, verified, prepared, rows, fire_lifecycle_hook):
    from hermes_cli import kanban_db as kb
    task_id = captured['id']
    task = repo.get(conn, store, task_id)
    if not _matches(task, captured) or _unsatisfied(conn, store, task_id):
        store.command_result(conn, False)
        return None
    if expected_run_id is not None and task['current_run_id'] != int(expected_run_id):
        store.command_result(conn, False)
        return None
    if verify_on_connection(conn, store, task_id, verified)[1] or not record(conn, store, task, prepared):
        store.command_result(conn, False)
        return None
    repo.task_update(conn, store, task_id, status='done', result=result, completed_at=int(time.time()), claim_lock=None, claim_expires=None, worker_pid=None, block_kind=None, block_recurrences=0, consecutive_failures=0, last_failure_error=None)
    for row in rows:
        insert_attachment(conn, store, task_id, **row, uploaded_by='kanban_complete')
    run_id, handoff = _close_completed(conn, store, task, result, summary, metadata)
    event_summary = handoff or (kb._REVIEW_APPROVED_NOTE if task['status'] == 'review' else None)
    repo.event(conn, store, task_id, 'completed', kb._completed_event_payload(result, event_summary, verified, metadata), run_id)
    steps = [dict(kind='phantom', task_id=task_id, run_id=run_id, summary=summary, result=result, verified=verified), dict(kind='ready'), dict(kind='workspace', task_id=task_id)]
    if fire_lifecycle_hook:
        steps.append(hook_step(store, task, 'kanban_task_completed', run_id, summary=handoff))
    effect_id = enqueue(conn, store, steps)
    store.command_result(conn, True)
    return (run_id, handoff, effect_id)

def _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if _unsatisfied(conn, store, task_id):
            store.command_result(conn, False)
            return None
        if task is None or task['status'] not in {'running', 'ready', 'blocked', 'review'}:
            store.command_result(conn, False)
            return None
        if expected_run_id is not None and task['current_run_id'] != int(expected_run_id):
            store.command_result(conn, False)
            return None
    cards = tuple(created_cards or ())
    verified = kb._gate_created_cards(store, task_id, cards, summary or result)
    kb._gate_empty_completion(store, task_id, result=result, summary=summary)
    if expected_run_id is None and (not force) and kb._claim_is_live(task):
        raise kb.LiveClaimError(task_id)
    prepared = prepare(store, task, expected_run_id, metadata)
    if prepared is False:
        return None
    if prepared is not None and (not prepared[1]['ok']):
        with store.write() as conn:
            current = repo.get(conn, store, task_id)
            if _matches(current, task):
                record(conn, store, current, prepared)
            store.command_result(conn, False)
        return None
    metadata = kb._merge_completion_prose_artifacts(store, task_id, metadata, summary=summary, result=result)
    metadata = dict(metadata) if isinstance(metadata, dict) else metadata
    return (task, verified, metadata, prepared)

def complete_task(store, task_id, *, result=None, summary=None, metadata=None, created_cards=None, expected_run_id=None, fire_lifecycle_hook=True, force=False):
    from hermes_cli import kanban_db as kb
    preparation = _prepare_completion(store, task_id, result, summary, metadata, created_cards, expected_run_id, force)
    if preparation is None:
        return False
    task, verified, metadata, prepared = preparation
    from hermes_db.domains.kanban.postgres.files import local_files_lock
    with local_files_lock(store.scope.profile_home):
        staged, rows = _prepare_files(store, task_id, metadata)
        durable = False
        try:
            with store.write() as conn:
                completed = _write_completion(conn, store, task, expected_run_id, result, summary, metadata, verified, prepared, rows, fire_lifecycle_hook)
            durable = completed is not None
        except UnknownCommitError:
            durable = True
            raise
        finally:
            if staged and (not durable):
                from hermes_db.domains.kanban.postgres.files import discard_copies
                discard_copies(store, staged)
    if completed is None:
        return False
    after_commit(store, completed[2])
    return True

def verify_on_connection(conn, store, task_id, claimed_ids):
    ordered = list(dict.fromkeys(str(value).strip() for value in claimed_ids if str(value).strip()))
    task = repo.get(conn, store, task_id)
    if task is None:
        return ([], ordered)
    found = {decode_text(tid): decode_text(creator) for tid, creator in conn.execute(select(tasks.c.id, tasks.c.created_by).where(repo.scope(tasks, store), tasks.c.id.in_([encode_text(value) for value in ordered])))}
    children = set(repo.linked_ids(conn, store, task_id, parents=False))
    verified, phantom = ([], [])
    for tid in ordered:
        creator = found.get(tid)
        trusted = creator is not None and (task['assignee'] and creator == task['assignee'] or creator == task_id or tid in children)
        (verified if trusted else phantom).append(tid)
    return (verified, phantom)

def _verify_created_cards(store, completing_task_id, claimed_ids):
    with store.read() as conn:
        return verify_on_connection(conn, store, completing_task_id, claimed_ids or ())

def _audit(conn, store, task_id, kind, payload, error):
    from hermes_db.domains.kanban.postgres.receipts import refusal
    if repo.get(conn, store, task_id) is not None:
        repo.event(conn, store, task_id, kind, payload)
    store.command_result(conn, refusal(error))

def _gate_created_cards(store, task_id, created_cards, preview_text):
    from hermes_cli import kanban_db as kb
    if not created_cards:
        return []
    with store.write() as conn:
        verified, phantom = verify_on_connection(conn, store, task_id, created_cards)
        if phantom:
            error = kb.HallucinatedCardsError(phantom, task_id)
            _audit(conn, store, task_id, 'completion_blocked_hallucination', {'phantom_cards': phantom, 'verified_cards': verified, 'summary_preview': kb._first_line(preview_text, 200) or None}, error)
    if phantom:
        raise error
    return verified

def _gate_empty_completion(store, task_id, *, result, summary):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] == 'review':
            return
        if any(kb._substantive_text(value) for value in (result, summary, row['result'])):
            return
        error = kb.EmptyCompletionError(task_id)
        _audit(conn, store, task_id, 'completion_blocked_empty_result', {'result_preview': kb._first_line(result, 200) or None, 'summary_preview': kb._first_line(summary, 200) or None}, error)
    raise error

def _phantom_ids(conn, store, text):
    from hermes_cli.kanban_db import _TASK_ID_PROSE_RE
    ids = list(dict.fromkeys(_TASK_ID_PROSE_RE.findall(text or '')))
    found = {decode_text(tid) for tid in conn.scalars(select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.id.in_([encode_text(value) for value in ids])))}
    return [tid for tid in ids if tid not in found]

def _scan_prose_for_phantom_ids(store, text):
    with store.read() as conn:
        return _phantom_ids(conn, store, text)

def _flag_phantom_prose_refs(store, task_id, run_id, summary, result, verified_cards):
    import json
    from hermes_db.tables.kanban import events
    text = ' '.join(value for value in (summary, result) if value)
    if not text:
        return
    with store.write() as conn:
        phantom = [value for value in _phantom_ids(conn, store, text) if value not in set(verified_cards)]
        if not phantom:
            return
        payload = {'phantom_refs': phantom, 'source': 'completion_summary'}
        kind = 'suspected_hallucinated_references'
        existing = conn.scalar(select(events.c.id).where(repo.key(store, task_id, events), events.c.run_id == run_id, events.c.kind == encode_text(kind), events.c.payload == encode_text(json.dumps(payload, ensure_ascii=False))).limit(1))
        if existing is None:
            repo.event(conn, store, task_id, kind, payload, run_id)

def snapshot(task):
    return tuple(task[key] for key in ('current_run_id', 'status', 'completion_contract', 'assignee'))

def prepare(store, task, expected_run_id, metadata):
    from hermes_cli import kanban_pr_acceptance as acceptance
    contract = task['completion_contract']
    if not contract or contract == 'local-only':
        return None
    if expected_run_id is not None and task['current_run_id'] != expected_run_id:
        return False
    published_pr = metadata.get('published_pr') if isinstance(metadata, dict) else None
    match = acceptance._PR.fullmatch(published_pr) if isinstance(published_pr, str) else None
    captured = snapshot(task)
    if match and contract == match[1]:
        with store.write() as conn:
            current = repo.get(conn, store, task['id'])
            if current is None or snapshot(current) != captured:
                return False
            repo.task_update(conn, store, task['id'], completion_contract=published_pr)
        task['completion_contract'] = contract = published_pr
        captured = snapshot(task)
    receipt = acceptance.collect_acceptance(contract, published_pr, assignee=task['assignee'])
    return (captured, receipt)

def record(conn, store, task, prepared):
    if prepared is None:
        return True
    captured, receipt = prepared
    if snapshot(task) != captured:
        return False
    repo.event(conn, store, task['id'], 'pr_acceptance', receipt, task['current_run_id'])
    if not receipt['ok']:
        detail = f"PR acceptance {receipt['classification']}: {receipt.get('detail', '')} {receipt['recovery']}"
        repo.task_update(conn, store, task['id'], last_failure_error=detail)
    return receipt['ok']

def edit_result(store, task_id, *, title, body, priority, result, summary, metadata, board):
    from hermes_cli import kanban_db as kb
    values = {name: value for name, value in (('title', title), ('body', body), ('priority', priority), ('result', result)) if value is not None}
    changed = list(values) + ['summary'] + (['metadata'] if metadata is not None else [])
    handoff = summary if summary is not None else result
    with store.write() as conn:
        task = repo.get(conn, store, task_id)
        if task is None or task['status'] != 'done':
            return False
        repo.task_update(conn, store, task_id, **values)
        if priority is not None:
            repo.event(conn, store, task_id, 'reprioritized', {'priority': priority})
        run_id = conn.scalar(select(runs.c.id).where(repo.key(store, task_id, runs), runs.c.outcome == b'completed').order_by(func.coalesce(runs.c.ended_at, runs.c.started_at, 0).desc(), runs.c.id.desc()).limit(1))
        if run_id is None:
            run_id = run_repo.synthesize(conn, store, task, outcome='completed', summary=handoff, metadata=metadata)
        else:
            updates = {'summary': handoff}
            if metadata is not None:
                updates['metadata'] = json.dumps(metadata, ensure_ascii=False)
            run_repo.update_run(conn, store, run_id, **updates)
        fields = ['result', 'summary'] + (['metadata'] if metadata is not None else [])
        repo.event(conn, store, task_id, 'edited', {'fields': fields, 'result_len': len(result) if result else 0, 'summary': kb._first_line(handoff, 400) or None}, run_id)
    kb.notify_task_updated(store, task_id, changed, board=board)
    return True
