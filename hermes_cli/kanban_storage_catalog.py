"""Application board metadata, task preparation, notifications and worker effects."""
import json
import time
from pathlib import Path
from hermes_cli import kanban_workflow as _storage_shared_1_
from hermes_db.domains.kanban import rules as _storage_shared_1
from hermes_db.domains.kanban.postgres import catalog as db, files as db_files, repository as repo, workspaces, runs as run_repo
from hermes_db.core.values import encode_text, decode_text
from hermes_cli import kanban_storage_files as files
from hermes_cli.kanban_storage_files import local_files_lock
from hermes_cli.kanban_storage_owner import canonical_path



def _metadata(row, slug, files):
    meta = files.read_metadata_file(slug)
    meta['db_path'] = None
    if row is not None:
        meta['archived'] = bool(row['archived'])
    return meta


def resolve_board(store, slug):
    row = db.lookup_board(store, slug)
    if row is None and slug == 'default':
        create_board(store, slug)
        row = db.lookup_board(store, slug)
    if row is None:
        raise ValueError(f'kanban board {slug!r} does not exist; create it with `hermes kanban boards create {slug}`')
    if row['archived']:
        from hermes_db.errors import StorageBusyError
        importing = db.pending_board_import(store, row['board_id'])
        if importing is not None:
            raise StorageBusyError('Board import files are pending; resume the original file job before opening the Board')
    if row['archived']:
        raise ValueError(f'kanban board {slug!r} is archived; refusing to recreate its database')
    return row['board_id']


def read_board_metadata(store, board=None):

    slug = _storage_shared_1._slug_or_default(board)
    row = db.lookup_board(store, slug)
    return _metadata(row, slug, store.files)


def write_board_metadata(store, board, *, name=None, description=None, icon=None, color=None, archived=None, default_workdir=None, project_id=None):

    store.mutation_guard()
    slug = _storage_shared_1._slug_or_default(board)
    values = dict(name=name, description=description, icon=icon, color=color, archived=archived, default_workdir=default_workdir, project_id=project_id)
    db.update_board_metadata_row(store, slug, archived)
    with local_files_lock(store.scope.profile_home):
        store.files.write_metadata_file(slug, **values)
        return read_board_metadata(store, slug)


def create_board(store, slug, *, name=None, description=None, icon=None, color=None, default_workdir=None, project_id=None):

    store.mutation_guard()
    slug = _storage_shared_1._require_slug(slug)
    board_id = db.create_board_row(store, slug)
    with local_files_lock(store.scope.profile_home):
        current = db.lookup_board(store, slug)
        if current is None or current['archived'] or current['board_id'] != board_id:
            raise ValueError('Board generation was retired before its file configuration could be written')
        store.files.write_metadata_file(slug, name=name, description=description, icon=icon, color=color, default_workdir=default_workdir, project_id=project_id, archived=False)
        return read_board_metadata(store, slug)


def list_boards(store, *, include_archived=True):
    rows = db.board_metadata_rows(store, include_archived)
    return [_metadata(row, slug, store.files) for slug, row in rows]


def remove_board(store, slug, *, archive=True):

    store.mutation_guard()
    slug = _storage_shared_1._require_slug(slug)
    if slug == 'default':
        raise ValueError("the 'default' board cannot be removed")
    captured = db.lookup_board(store, slug)
    if captured is None:
        pending = db_files.pending_delete(store, slug) if not archive else None
        if pending is not None:
            return {'slug': slug, 'action': 'deleted', **files.run_job(store, pending)}
        raise ValueError(f'board {slug!r} does not exist')
    files.settle_import_stage(store, captured['board_id'])
    prepared = files.prepare(store, captured)
    row = db.retire_board_row(store, slug, captured, prepared, archive)
    if store.policy.get_current_board() == slug:
        store.policy.clear_current_board()
    result = files.run_job(store, row['board_id'])
    return {'slug': slug, 'action': 'archived' if archive else 'deleted', **result}


def _workspace(store, fields):

    kind = fields.get('workspace_kind')
    project_id = fields.get('project_id')
    meta = store.files.read_board_metadata(store.slug)
    if project_id is None and kind != 'scratch':
        project_id = (meta.get('project_id') or '').strip() or None
    if kind is None:
        kind = 'scratch'
    if kind not in _storage_shared_1.VALID_WORKSPACE_KINDS:
        raise ValueError(f'workspace_kind must be one of {sorted(_storage_shared_1.VALID_WORKSPACE_KINDS)}, got {kind!r}')
    branch = str(fields['branch_name']).strip() or None if fields.get('branch_name') is not None else None
    if branch and kind != 'worktree':
        raise ValueError('branch_name is only valid for worktree workspaces')
    project_id, project, project_repo, kind = store.policy.resolve_project_link(store, project_id, fields.get('project_source_task_id'), kind, fields.get('workspace_path'))
    path = fields.get('workspace_path')
    if path is None and project_repo is None and (kind in {'dir', 'worktree'}):
        path = meta.get('default_workdir') or None
    return (dict(project_id=project_id, workspace_kind=kind, workspace_path=path, branch_name=branch), project, project_repo)


def prepare(store, fields):

    from hermes_db.domains.kanban.rules import validate_contract
    title = fields['title']
    if not title or not title.strip():
        raise ValueError('title is required')
    if fields.get('board') is not None and _storage_shared_1._require_slug(fields['board']) != store.slug:
        raise ValueError('task Board must match its acquired Board resource')
    initial = fields.get('initial_status', 'running')
    if initial not in _storage_shared_1.VALID_INITIAL_STATUSES:
        raise ValueError(f'initial_status must be one of {sorted(_storage_shared_1.VALID_INITIAL_STATUSES)}')
    model, provider = _storage_shared_1._validate_model_override(fields.get('model_override'), fields.get('provider_override'))
    skills = store.policy.normalize_task_skills(fields.get('skills'))
    values = {name: fields.get(name) for name in ('body', 'created_by', 'tenant', 'session_id', 'idempotency_key')}
    values.update(title=title.strip(), assignee=_storage_shared_1._canonical_assignee(fields.get('assignee')), priority=fields.get('priority', 0), model_override=model, provider_override=provider, reasoning_effort=_storage_shared_1.normalize_reasoning_effort(fields.get('reasoning_effort')), skills=json.dumps(skills) if skills is not None else None, goal_mode=int(bool(fields.get('goal_mode'))), completion_contract=validate_contract(fields.get('completion_contract')))
    values.update({name: _storage_shared_1._opt_int(fields.get(name)) for name in ('max_runtime_seconds', 'max_retries', 'goal_max_turns')})
    workspace, project, project_repo = _workspace(store, fields)
    values.update(workspace)
    path_keys = (canonical_path(workspace['workspace_path']), canonical_path(Path(project_repo) / '.worktrees') if project_repo is not None else None)
    return (values, project, project_repo, path_keys)


def _insert(conn, store, values, project, project_repo, path_keys):

    for _attempt in range(2):
        task_id = _storage_shared_1._new_task_id()
        candidate = dict(values, id=task_id)
        path_key = path_keys[0]
        if project is not None and values['workspace_kind'] == 'worktree':
            if project_repo is not None:
                candidate['workspace_path'] = str(Path(project_repo) / '.worktrees' / task_id)
                path_key = str(Path(path_keys[1]) / task_id)
            candidate['branch_name'] = candidate['branch_name'] or store.policy.project_branch_name(project, task_id, values['title'])
        inserted = db.insert_task_candidate(conn, store, candidate)
        if inserted is not None:
            workspaces.register(conn, store, task_id, path_key)
            return (task_id, candidate)
    raise ValueError('could not allocate a unique Kanban task ID')


def insert_prepared(conn, store, fields, values, project, project_repo, path_keys):
    parents = tuple(pid for pid in fields.get('parents', ()) if pid)
    values = dict(values, created_at=int(time.time()))
    values['status'], parent_rows = db._initial_state(conn, store, parents, fields, values)
    creator = fields.get('creator_task_id')
    if creator and values['session_id'] is None:
        origin = repo.get(conn, store, creator)
        values['session_id'] = origin['session_id'] if origin else None
    task_id, values = _insert(conn, store, values, project, project_repo, path_keys)
    for pid in parents:
        repo.link(conn, store, pid, task_id)
    payload = {name: values.get(name) for name in ('assignee', 'status', 'tenant', 'workspace_kind', 'workspace_path', 'branch_name', 'project_id', 'model_override', 'provider_override')}
    payload.update(parents=list(parents), creator_task_id=creator, skills=json.loads(values['skills']) if values['skills'] else None, goal_mode=bool(values['goal_mode']) or None)
    repo.event(conn, store, task_id, 'created', payload)
    if values['status'] == 'blocked':
        repo.event(conn, store, task_id, 'blocked', {'reason': 'initial_status', 'status': 'blocked', 'actor': values['created_by'] or 'user'})
    gating = [pid for pid, row in parent_rows.items() if row['status'] not in {'done', 'archived'}]
    if values['status'] == 'todo' and gating:
        repo.event(conn, store, task_id, 'dependency_wait', {'reason': 'parent_not_done', 'parent': gating[0]})
    from hermes_db.domains.kanban.postgres.notify import inherit
    inherit(conn, store, task_id, [creator] if creator else (), created_at=values['created_at'])
    inherit(conn, store, task_id, parents, created_at=values['created_at'])
    return task_id


def create_task(store, **fields):
    values, project, project_repo, path_keys = prepare(store, fields)
    fields['parents'] = tuple(fields.get('parents', ()))
    with store.write() as conn:
        idempotency = fields.get('idempotency_key')
        if idempotency:
            existing = db.existing_live_task(conn, store, idempotency)
            if existing is not None:
                return store.command_result(conn, decode_text(existing))
        return store.command_result(conn, insert_prepared(conn, store, fields, values, project, project_repo, path_keys))


def notify_task_updated(store, task_id, changed_fields, *, board=None):

    if store.observers.kanban_observer_consumed('on_kanban_task_updated'):
        task = db.get_task(store, task_id)
        store.observers.fire_kanban_lifecycle_hook('on_kanban_task_updated', task_id, board=board or store.slug, assignee=task.assignee if task else None, run_id=task.current_run_id if task else None, changed_fields=list(changed_fields))


def assign_task(store, task_id, profile):

    profile = _storage_shared_1._canonical_assignee(profile)
    ok = db.assign_task_row(store, task_id, profile)
    if not ok:
        return False
    notify_task_updated(store, task_id, ('assignee',))
    return True


def _override(store, task_id, values, kind, payload, archived_msg):

    ok = db.override_task_row(store, task_id, values, kind, payload, archived_msg)
    if not ok:
        return False
    notify_task_updated(store, task_id, tuple(values))
    return True


def set_model_override(store, task_id, model, provider=None):
    from hermes_db.domains.kanban.rules import _validate_model_override
    model, provider = _validate_model_override(model, provider)
    return _override(store, task_id, {'model_override': model, 'provider_override': provider}, 'model_override_set', {'model': model, 'provider': provider}, 'cannot set model override')


def set_reasoning_effort(store, task_id, effort):
    from hermes_db.domains.kanban.rules import normalize_reasoning_effort
    effort = normalize_reasoning_effort(effort)
    return _override(store, task_id, {'reasoning_effort': effort}, 'reasoning_effort_set', {'reasoning_effort': effort}, 'cannot set reasoning effort')


def edit_task(store, task_id, *, title=None, body=None, priority=None, result=None, summary=None, metadata=None, board=None):

    if result is not None:
        from hermes_cli.kanban_storage_completion import edit_result
        return edit_result(store, task_id, title=title, body=body, priority=priority, result=result, summary=summary, metadata=metadata, board=board)
    values = {name: value for name, value in (('title', title), ('body', body), ('priority', priority)) if value is not None}
    if not values:
        return False
    ok = db.edit_task_row(store, task_id, values, priority)
    if not ok:
        return False
    notify_task_updated(store, task_id, list(values), board=board)
    return True


def known_assignees(store):

    on_disk = set(store.policy.list_profiles_on_disk())
    counts = db.board_stats(store)['by_assignee']
    return [{'name': name, 'on_disk': name in on_disk, 'counts': counts.get(name, {})} for name in sorted(on_disk | set(counts))]


def _set_status_direct(store, task_id, new_status):

    if new_status not in _storage_shared_1_.DEFAULT_STATUSES:
        raise ValueError('unknown task status')
    changed = db.transition_task(store, task_id, new_status)
    if changed is None:
        return False
    effective, result = changed
    terminate(store, result)
    if effective in {'done', 'ready', 'review'}:
        store.recompute_ready()
    return True


def archive_task(store, task_id, *, signal_fn=None):

    captured = db.archive_task_row(store, task_id)
    if captured is None:
        return False
    row, run_id = captured
    if row['status'] == 'running':
        termination = store.processes.terminate_reclaimed_worker(row['worker_pid'], row['claim_lock'], signal_fn=signal_fn, started_at=row['worker_started_at'])
        db.record_archive_termination(store, task_id, termination, run_id)
    store.recompute_ready()
    from hermes_cli.kanban_storage_workspaces import _cleanup_workspace
    _cleanup_workspace(store, task_id)
    return True


def decompose_triage_task(store, task_id, *, root_assignee, children, author=None, auto_promote=True):
    from hermes_db.domains.kanban.rules import _canonical_assignee
    from hermes_db.domains.kanban.rules import _validate_children_graph
    if not children:
        return None
    root_assignee = _canonical_assignee(root_assignee)
    _validate_children_graph(children)
    from hermes_cli.kanban_storage_owner import canonical_path
    path_keys = [canonical_path(child.get('workspace_path')) for child in children]
    ids = db.decompose_task_rows(store, task_id, root_assignee, children, author, path_keys)
    if auto_promote:
        db.recompute_ready(store)
    return ids


def terminate(store, result):

    for pid, lock, birth in result['terminations']:
        store.processes.terminate_reclaimed_worker(pid, lock, started_at=birth)


def invalidate_descendants_for_parent_reopen(store, task_id, *, author):
    result = db.invalidate_descendant_rows(store, task_id, author)
    terminate(store, result)
    return result
