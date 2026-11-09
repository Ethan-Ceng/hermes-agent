"""Kanban catalog workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_cli import kanban_workflow as _storage_shared_1_
from hermes_db.domains.kanban import rules as _storage_shared_1
from uuid import uuid4
from sqlalchemy import and_, delete, select, update, func
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.kanban import kanban_boards as boards, kanban_board_names as names, kanban_board_locks as locks, tasks, comments, events, links, runs
import json
import time
from pathlib import Path
from hermes_db.domains.kanban.postgres import repository as repo, workspaces, runs as run_repo
from hermes_db.core.values import encode_text, decode_text

def _scope(table, store):
    return table.c.store_id == store.scope.require_store_id()

def _registry_lock(conn, store):
    conn.execute(insert(locks).values(store_id=store.scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks).where(_scope(locks, store)).with_for_update()).one()

def _lookup(conn, store, slug):
    return conn.execute(select(boards).join(names, and_(boards.c.store_id == names.c.store_id, boards.c.board_id == names.c.board_id)).where(_scope(boards, store), names.c.slug == slug)).mappings().one_or_none()

def _metadata(row, slug, files):
    meta = files.read_metadata_file(slug)
    meta['db_path'] = None
    if row is not None:
        meta['archived'] = bool(row['archived'])
    return meta

def _save(conn, store, slug, row, archived, *, new_board_id=None):
    if row is None:
        board_id = new_board_id or ('default' if slug == 'default' else uuid4().hex)
        conn.execute(boards.insert().values(store_id=store.scope.require_store_id(), board_id=board_id, slug=slug, archived=int(archived)))
        conn.execute(insert(names).values(store_id=store.scope.require_store_id(), slug=slug, board_id=board_id).on_conflict_do_update(index_elements=[names.c.store_id, names.c.slug], set_={'board_id': board_id}))
    else:
        board_id = row['board_id']
        conn.execute(update(boards).where(_scope(boards, store), boards.c.board_id == board_id).values(archived=int(archived)))
    return board_id

def resolve_board(store, slug):
    with store.read() as conn:
        row = _lookup(conn, store, slug)
    if row is None and slug == 'default':
        create_board(store, slug)
        with store.read() as conn:
            row = _lookup(conn, store, slug)
    if row is None:
        raise ValueError(f'kanban board {slug!r} does not exist; create it with `hermes kanban boards create {slug}`')
    if row['archived']:
        from hermes_db.tables.kanban_file_jobs import file_jobs
        from hermes_db.errors import StorageBusyError
        with store.read() as conn:
            importing = conn.scalar(select(file_jobs.c.board_id).where(file_jobs.c.store_id == store.scope.require_store_id(), file_jobs.c.board_id == row['board_id'], file_jobs.c.action == 'import', file_jobs.c.state != 'done'))
        if importing is not None:
            raise StorageBusyError('Board import files are pending; resume the original file job before opening the Board')
    if row['archived']:
        raise ValueError(f'kanban board {slug!r} is archived; refusing to recreate its database')
    return row['board_id']

def read_board_metadata(store, board=None):

    slug = _storage_shared_1._slug_or_default(board)
    with store.read() as conn:
        row = _lookup(conn, store, slug)
    return _metadata(row, slug, store.files)

def board_exists(store, board=None):

    slug = _storage_shared_1._slug_or_default(board)
    with store.read() as conn:
        return slug == _storage_shared_1.DEFAULT_BOARD or _lookup(conn, store, slug) is not None

def write_board_metadata(store, board, *, name=None, description=None, icon=None, color=None, archived=None, default_workdir=None, project_id=None):

    store.mutation_guard()
    slug = _storage_shared_1._slug_or_default(board)
    values = dict(name=name, description=description, icon=icon, color=color, archived=archived, default_workdir=default_workdir, project_id=project_id)
    with store.write() as conn:
        from hermes_db.domains.kanban.postgres.files import lock_files, local_files_lock, require_settled_slug
        lock_files(conn, store)
        _registry_lock(conn, store)
        require_settled_slug(conn, store, slug)
        row = _lookup(conn, store, slug)
        if row is not None and row['archived'] and (archived is False):
            raise ValueError('Recreate an archived Board with create_board; its old generation is immutable')
        if row is not None:
            conn.execute(select(boards).where(_scope(boards, store), boards.c.board_id == row['board_id']).with_for_update()).one()
        state = bool(row['archived']) if row is not None and archived is None else bool(archived)
        _save(conn, store, slug, row, state)
    with local_files_lock(store.scope.profile_home):
        store.files.write_metadata_file(slug, **values)
        return read_board_metadata(store, slug)

def create_board(store, slug, *, name=None, description=None, icon=None, color=None, default_workdir=None, project_id=None):

    store.mutation_guard()
    slug = _storage_shared_1._require_slug(slug)
    with store.write() as conn:
        from hermes_db.domains.kanban.postgres.files import lock_files, local_files_lock, require_settled_slug
        lock_files(conn, store)
        _registry_lock(conn, store)
        require_settled_slug(conn, store, slug)
        row = _lookup(conn, store, slug)
        if row is not None and row['archived']:
            row = None
        board_id = _save(conn, store, slug, row, False)
    with local_files_lock(store.scope.profile_home):
        with store.read() as conn:
            current = _lookup(conn, store, slug)
        if current is None or current['archived'] or current['board_id'] != board_id:
            raise ValueError('Board generation was retired before its file configuration could be written')
        store.files.write_metadata_file(slug, name=name, description=description, icon=icon, color=color, default_workdir=default_workdir, project_id=project_id, archived=False)
        return read_board_metadata(store, slug)

def list_boards(store, *, include_archived=True):
    with store.read() as conn:
        slugs = list(conn.scalars(select(names.c.slug).where(_scope(names, store)).order_by(names.c.slug)))
        rows = [('default', _lookup(conn, store, 'default'))]
        for slug in slugs:
            if slug == 'default':
                continue
            row = _lookup(conn, store, slug)
            if include_archived or not row['archived']:
                rows.append((slug, row))
    return [_metadata(row, slug, store.files) for slug, row in rows]

def remove_board(store, slug, *, archive=True):

    from hermes_db.domains.kanban.postgres import files
    store.mutation_guard()
    slug = _storage_shared_1._require_slug(slug)
    if slug == 'default':
        raise ValueError("the 'default' board cannot be removed")
    with store.read() as conn:
        captured = _lookup(conn, store, slug)
    if captured is None:
        pending = files.pending_delete(store, slug) if not archive else None
        if pending is not None:
            return {'slug': slug, 'action': 'deleted', **files.run_job(store, pending)}
        raise ValueError(f'board {slug!r} does not exist')
    files.settle_import_stage(store, captured['board_id'])
    prepared = files.prepare(store, captured)
    with store.write() as conn:
        files.lock_files(conn, store)
        _registry_lock(conn, store)
        row = _lookup(conn, store, slug)
        if row is None or row['board_id'] != captured['board_id']:
            raise ValueError('Board generation changed before retirement')
        condition = and_(_scope(boards, store), boards.c.board_id == row['board_id'])
        conn.execute(select(boards).where(condition).with_for_update()).one()
        files.record(conn, store, row, prepared, archive=archive)
        conn.execute(update(boards).where(condition).values(archived=1) if archive else delete(boards).where(condition))
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
    path_keys = (workspaces.canonical_path(workspace['workspace_path']), workspaces.canonical_path(Path(project_repo) / '.worktrees') if project_repo is not None else None)
    return (values, project, project_repo, path_keys)

def _initial_state(conn, store, parents, fields, values):
    rows = {pid: repo.get(conn, store, pid) for pid in parents}
    missing = [pid for pid, row in rows.items() if row is None]
    if missing:
        raise ValueError(f"unknown parent task(s): {', '.join(missing)}")
    if values['tenant'] is None:
        values['tenant'] = next((row['tenant'] for row in rows.values() if row['tenant']), None)
    if fields.get('initial_status') == 'blocked':
        return ('blocked', rows)
    if fields.get('triage'):
        return ('triage', rows)
    return ('todo' if any(row['status'] != 'done' for row in rows.values()) else 'ready', rows)

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
        inserted = conn.scalar(insert(tasks).values(**repo.owner(store), **repo.encode_task(candidate)).on_conflict_do_nothing(index_elements=[tasks.c.store_id, tasks.c.board_id, tasks.c.id]).returning(tasks.c.id))
        if inserted is not None:
            workspaces.register(conn, store, task_id, path_key)
            return (task_id, candidate)
    raise ValueError('could not allocate a unique Kanban task ID')

def insert_prepared(conn, store, fields, values, project, project_repo, path_keys):
    parents = tuple(pid for pid in fields.get('parents', ()) if pid)
    values = dict(values, created_at=int(time.time()))
    values['status'], parent_rows = _initial_state(conn, store, parents, fields, values)
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
            existing = conn.scalar(select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.idempotency_key == encode_text(idempotency), tasks.c.status != b'archived').order_by(tasks.c.created_at.desc(), tasks.c.id.desc()).limit(1))
            if existing is not None:
                return store.command_result(conn, decode_text(existing))
        return store.command_result(conn, insert_prepared(conn, store, fields, values, project, project_repo, path_keys))

def get_task(store, task_id):

    with store.read() as conn:
        row = repo.get(conn, store, task_id)
        return store.result_values.task(row) if row is not None else None

def _sort(order_by):
    from hermes_db.domains.kanban.rules import VALID_SORT_ORDERS
    orders = {'created': (tasks.c.created_at.asc(), tasks.c.id.asc()), 'created-desc': (tasks.c.created_at.desc(), tasks.c.id.desc()), 'priority': (tasks.c.priority.desc(), tasks.c.created_at.asc()), 'priority-desc': (tasks.c.priority.asc(), tasks.c.created_at.asc()), 'status': (tasks.c.status.asc(), tasks.c.created_at.asc()), 'assignee': (tasks.c.assignee.asc().nulls_first(), tasks.c.created_at.asc()), 'title': (tasks.c.title.asc(), tasks.c.id.asc()), 'updated': (tasks.c.started_at.desc().nulls_last(), tasks.c.created_at.desc()), 'completed-desc': (tasks.c.completed_at.desc().nulls_last(), tasks.c.id.desc())}
    name = order_by.strip().lower() if order_by is not None else 'priority'
    if name not in orders:
        raise ValueError(f'order_by must be one of {sorted(VALID_SORT_ORDERS)}')
    return orders[name]

def list_tasks(store, *, assignee=None, status=None, tenant=None, session_id=None, include_archived=False, limit=None, order_by=None, workflow_template_id=None, current_step_key=None):
    from hermes_cli.kanban_workflow import DEFAULT_STATUSES as VALID_STATUSES
    from hermes_db.domains.kanban.rules import _canonical_assignee
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f'status must be one of {sorted(VALID_STATUSES)}')
    query = select(tasks).where(repo.scope(tasks, store))
    for name, value in (('assignee', _canonical_assignee(assignee)), ('status', status), ('tenant', tenant), ('session_id', session_id), ('workflow_template_id', workflow_template_id), ('current_step_key', current_step_key)):
        if value is not None:
            query = query.where(tasks.c[name] == encode_text(value))
    if not include_archived and status != 'archived':
        query = query.where(tasks.c.status != b'archived')
    if limit and int(limit) >= 0:
        query = query.limit(int(limit))
    with store.read() as conn:
        return [store.result_values.task(repo.decode_task(row)) for row in conn.execute(query.order_by(*_sort(order_by))).mappings()]

def notify_task_updated(store, task_id, changed_fields, *, board=None):

    if store.observers.kanban_observer_consumed('on_kanban_task_updated'):
        task = get_task(store, task_id)
        store.observers.fire_kanban_lifecycle_hook('on_kanban_task_updated', task_id, board=board or store.slug, assignee=task.assignee if task else None, run_id=task.current_run_id if task else None, changed_fields=list(changed_fields))

def assign_task(store, task_id, profile):

    profile = _storage_shared_1._canonical_assignee(profile)
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None:
            return False
        if row['claim_lock'] is not None and row['status'] == 'running':
            from hermes_cli.kanban_errors import TaskAlreadyClaimedError
            raise TaskAlreadyClaimedError(f'cannot reassign {task_id}: currently running (claimed). Wait for completion or reclaim the stale lock first.')
        values = {'assignee': profile}
        if row['assignee'] != profile:
            values.update(consecutive_failures=0, last_failure_error=None)
        repo.task_update(conn, store, task_id, **values)
        repo.event(conn, store, task_id, 'assigned', {'assignee': profile, 'from': row['assignee']})
    store.notify_task_updated(task_id, ('assignee',))
    return True

def _override(store, task_id, values, kind, payload, archived_msg):

    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None:
            return False
        if row['status'] == 'archived':
            raise RuntimeError(f'{archived_msg} on archived task {task_id}')
        repo.task_update(conn, store, task_id, **values)
        repo.event(conn, store, task_id, kind, payload)
    store.notify_task_updated(task_id, tuple(values))
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
        from hermes_db.domains.kanban.postgres.completion import edit_result
        return edit_result(store, task_id, title=title, body=body, priority=priority, result=result, summary=summary, metadata=metadata, board=board)
    values = {name: value for name, value in (('title', title), ('body', body), ('priority', priority)) if value is not None}
    if not values:
        return False
    with store.write() as conn:
        if repo.get(conn, store, task_id) is None:
            return False
        repo.task_update(conn, store, task_id, **values)
        if priority is not None:
            repo.event(conn, store, task_id, 'reprioritized', {'priority': priority})
        changed = [name for name in values if name != 'priority']
        if changed:
            repo.event(conn, store, task_id, 'edited', {'fields': changed})
    store.notify_task_updated(task_id, list(values), board=board)
    return True

def add_comment(store, task_id, author, body):
    if not body or not body.strip():
        raise ValueError('comment body is required')
    if not author or not author.strip():
        raise ValueError('comment author is required')
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        comment_id = repo.comment(conn, store, task_id, author.strip(), body.strip(), int(time.time()))
        repo.event(conn, store, task_id, 'commented', {'author': author, 'len': len(body)})
        return store.command_result(conn, comment_id)

def list_comments(store, task_id):

    with store.read() as conn:
        return [store.result_values.comment(repo.decode_record(row)) for row in conn.execute(select(comments).where(repo.key(store, task_id, comments)).order_by(comments.c.created_at, comments.c.id)).mappings()]

def list_comments_after(store, task_id, *, after_id=0):

    with store.read() as conn:
        return [store.result_values.comment(repo.decode_record(row)) for row in conn.execute(select(comments).where(repo.key(store, task_id, comments), comments.c.id > int(after_id)).order_by(comments.c.id)).mappings()]

def list_events(store, task_id):

    with store.read() as conn:
        return [store.result_values.event(repo.decode_record(row)) for row in conn.execute(select(events).where(repo.key(store, task_id, events)).order_by(events.c.created_at, events.c.id)).mappings()]

def _delete(store, task_id, *, archived_only):
    from hermes_db.domains.kanban.postgres.catalog import recompute_ready
    from hermes_db.tables.kanban_notify import subscriptions
    with store.write() as conn:
        condition = repo.key(store, task_id)
        if archived_only:
            condition = condition & (tasks.c.status == b'archived')
        count = conn.execute(delete(tasks).where(condition)).rowcount
        if count:
            conn.execute(delete(subscriptions).where(repo.key(store, task_id, subscriptions)))
    if count and (not archived_only):
        recompute_ready(store)
    return count > 0

def delete_task(store, task_id):
    return _delete(store, task_id, archived_only=False)

def delete_archived_task(store, task_id):
    return _delete(store, task_id, archived_only=True)

def board_stats(store):
    with store.read() as conn:
        rows = conn.execute(select(tasks.c.status, tasks.c.assignee, func.count().label('n')).where(repo.scope(tasks, store), tasks.c.status != b'archived').group_by(tasks.c.status, tasks.c.assignee)).all()
        oldest = conn.scalar(select(func.min(tasks.c.created_at)).where(repo.scope(tasks, store), tasks.c.status == b'ready'))
    by_status, by_assignee = ({}, {})
    for status, assignee, count in rows:
        status, assignee = (decode_text(status), decode_text(assignee))
        by_status[status] = by_status.get(status, 0) + count
        if assignee is not None:
            by_assignee.setdefault(assignee, {})[status] = count
    now = int(time.time())
    return dict(by_status=by_status, by_assignee=by_assignee, oldest_ready_age_seconds=now - oldest if oldest is not None else None, now=now)

def known_assignees(store):

    on_disk = set(store.policy.list_profiles_on_disk())
    counts = board_stats(store)['by_assignee']
    return [{'name': name, 'on_disk': name in on_disk, 'counts': counts.get(name, {})} for name in sorted(on_disk | set(counts))]

def gc_events(store, *, older_than_seconds=30 * 24 * 3600):
    from hermes_db.domains.kanban.rules import _retention_seconds
    cutoff = int(time.time()) - _retention_seconds(older_than_seconds)
    with store.write() as conn:
        terminal = select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.status.in_([b'done', b'archived']))
        return conn.execute(delete(events).where(repo.scope(events, store), events.c.created_at < cutoff, events.c.kind != b'decomposed', events.c.task_id.in_(terminal))).rowcount

def latest_event_id(store):
    with store.read() as conn:
        return conn.scalar(select(func.coalesce(func.max(events.c.id), 0)).where(repo.scope(events, store)))

def events_after(store, cursor, *, limit=200, with_task=False):
    columns = [events.c[name] for name in ('id', 'task_id', 'run_id', 'kind', 'payload', 'created_at')]
    statement = select(*columns).where(repo.scope(events, store), events.c.id > cursor)
    if with_task:
        statement = statement.add_columns(tasks.c.assignee, tasks.c.tenant).outerjoin(tasks, and_(tasks.c.store_id == events.c.store_id, tasks.c.board_id == events.c.board_id, tasks.c.id == events.c.task_id))
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(statement.order_by(events.c.id).limit(int(limit))).mappings()]

def tasks_by_ids(store, task_ids):
    ids = [encode_text(value) for value in dict.fromkeys(task_ids)]
    with store.read() as conn:
        return {decode_text(row['id']): repo.decode_task(row) for row in conn.execute(select(tasks).where(repo.scope(tasks, store), tasks.c.id.in_(ids))).mappings()}

def board_rollups(store):
    from hermes_db.domains.kanban.rules import summarize_board
    with store.read() as conn:
        link_rows = [repo.decode_record(row) for row in conn.execute(select(links.c.parent_id, links.c.child_id).where(repo.scope(links, store))).mappings()]
        comment_rows = [repo.decode_record(row) for row in conn.execute(select(comments.c.task_id, func.count().label('n')).where(repo.scope(comments, store)).group_by(comments.c.task_id)).mappings()]
        children = [repo.decode_record(row) for row in conn.execute(select(links.c.parent_id.label('pid'), tasks.c.status.label('cstatus')).join(tasks, and_(tasks.c.store_id == links.c.store_id, tasks.c.board_id == links.c.board_id, tasks.c.id == links.c.child_id)).where(repo.scope(links, store))).mappings()]
        tenants = [decode_text(value) for value in conn.scalars(select(tasks.c.tenant).where(repo.scope(tasks, store), tasks.c.tenant.is_not(None)).distinct().order_by(tasks.c.tenant))]
    return summarize_board(link_rows, comment_rows, children, tenants)

def board_status_counts(store):
    with store.read() as conn:
        return {decode_text(row.status): int(row.n) for row in conn.execute(select(tasks.c.status, func.count().label('n')).where(repo.scope(tasks, store)).group_by(tasks.c.status))}

def active_worker_rows(store):
    statement = select(runs.c.id.label('run_id'), runs.c.task_id, tasks.c.title.label('task_title'), tasks.c.status.label('task_status'), tasks.c.assignee.label('task_assignee'), *[runs.c[name] for name in ('profile', 'worker_pid', 'started_at', 'claim_lock', 'claim_expires', 'last_heartbeat_at', 'max_runtime_seconds')])
    statement = statement.join(tasks, and_(tasks.c.store_id == runs.c.store_id, tasks.c.board_id == runs.c.board_id, tasks.c.id == runs.c.task_id)).where(repo.scope(runs, store), runs.c.ended_at.is_(None), runs.c.worker_pid.is_not(None), tasks.c.status == b'running').order_by(runs.c.started_at)
    with store.read() as conn:
        return [repo.decode_record(row) for row in conn.execute(statement).mappings()]

def _parents_blocking_ready(store, task_id):
    with store.read() as conn:
        return [{name: row[name] for name in ('id', 'title', 'status')} for parent in repo.linked_ids(conn, store, task_id, parents=True) if (row := repo.require_task(conn, store, parent))['status'] != 'done']

def _transition(conn, store, task_id, new_status):
    previous = repo.get(conn, store, task_id)
    if previous is None:
        return None
    effective = new_status
    if previous['status'] == 'running' and new_status == 'ready':
        if run_repo.retry_status(conn, store, task_id, previous['current_run_id']) == 'review':
            effective = 'todo' if _unsatisfied(conn, store, task_id) else 'review'
    if effective == 'ready' and _unsatisfied(conn, store, task_id):
        return None
    values = dict(status=effective)
    if effective != 'running':
        values.update(claim_lock=None, claim_expires=None, worker_pid=None)
    repo.task_update(conn, store, task_id, **values)
    result = {'terminations': [], 'invalidated': []}
    run_id = None
    if previous['status'] == 'running' and effective != 'running' and previous['current_run_id']:
        run_id = run_repo.close_run(conn, store, previous, outcome='reclaimed', status='reclaimed', summary=f'status changed to {effective} (dashboard/direct)')
        result['terminations'].append((previous['worker_pid'], previous['claim_lock'], previous['worker_started_at']))
    repo.event(conn, store, task_id, 'status', {'status': effective, 'requested_status': new_status}, run_id)
    if previous['status'] in {'done', 'archived'} and effective not in {'done', 'archived'}:
        retracted = invalidate(conn, store, task_id, author='dashboard')
        result['terminations'].extend(retracted['terminations'])
    return (effective, result)

def _set_status_direct(store, task_id, new_status):

    if new_status not in _storage_shared_1_.DEFAULT_STATUSES:
        raise ValueError('unknown task status')
    with store.write() as conn:
        changed = _transition(conn, store, task_id, new_status)
    if changed is None:
        return False
    effective, result = changed
    terminate(store, result)
    if effective in {'done', 'ready', 'review'}:
        store.recompute_ready()
    return True

def diagnostic_snapshot(store, task_id=None, *, task_ids=None):
    condition = repo.key(store, task_id) if task_id is not None else repo.scope(tasks, store) & (tasks.c.status != b'archived')
    if task_ids is not None:
        condition = repo.scope(tasks, store) & tasks.c.id.in_([encode_text(value) for value in task_ids])
    with store.read() as conn:
        rows = [repo.decode_task(row) for row in conn.execute(select(tasks).where(condition)).mappings()]
        ids = [encode_text(row['id']) for row in rows]
        by_table = {}
        for table in (events, runs):
            by = {row['id']: [] for row in rows}
            records = conn.execute(select(table).where(repo.scope(table, store), table.c.task_id.in_(ids)).order_by(table.c.id)).mappings()
            for record in records:
                decoded = repo.decode_record(record)
                by[decoded['task_id']].append(decoded)
            by_table[table.name] = by
        contexts = {}
        for row in rows:
            context = {'parents': [], 'children': []}
            for bucket, parents in (('parents', True), ('children', False)):
                for linked in repo.linked_ids(conn, store, row['id'], parents=parents):
                    task = repo.require_task(conn, store, linked)
                    context[bucket].append({name: task[name] for name in ('id', 'title', 'status')})
            contexts[row['id']] = context
    return [(row, by_table[events.name][row['id']], by_table[runs.name][row['id']], contexts[row['id']]) for row in rows]

def _append_event(store, task_id, kind, payload=None, *, run_id=None):
    with store.write() as conn:
        repo.event(conn, store, task_id, kind, payload, run_id)

def archive_task(store, task_id, *, signal_fn=None):

    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] == 'archived':
            return False
        repo.task_update(conn, store, task_id, status='archived', claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None)
        run_id = run_repo.close_run(conn, store, row, outcome='reclaimed', status='reclaimed', summary='task archived with run still active')
        repo.event(conn, store, task_id, 'archived', None, run_id)
        store.command_result(conn, True)
    if row['status'] == 'running':
        termination = store.processes.terminate_reclaimed_worker(row['worker_pid'], row['claim_lock'], signal_fn=signal_fn, started_at=row['worker_started_at'])
        with store.write() as conn:
            repo.event(conn, store, task_id, 'archive_worker_termination', termination, run_id)
    store.recompute_ready()
    store._cleanup_workspace(task_id)
    return True

def parent_ids(store, task_id):
    with store.read() as conn:
        return repo.linked_ids(conn, store, task_id, parents=True)

def child_ids(store, task_id):
    with store.read() as conn:
        return repo.linked_ids(conn, store, task_id, parents=False)

def _unsatisfied(conn, store, task_id):
    rows = [repo.require_task(conn, store, pid) for pid in repo.linked_ids(conn, store, task_id, parents=True)]
    return [(row['id'], row['status']) for row in rows if row['status'] not in {'done', 'archived'}]

def unsatisfied_parents(store, task_id):
    with store.read() as conn:
        return _unsatisfied(conn, store, task_id)

def _would_cycle(conn, store, parent_id, child_id):
    seen, stack = (set(), [child_id])
    while stack:
        node = stack.pop()
        if node == parent_id:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(repo.linked_ids(conn, store, node, parents=False))
    return False

def link_tasks(store, parent_id, child_id, *, expected_child_run_id=None):
    if parent_id == child_id:
        raise ValueError('a task cannot depend on itself')
    with store.write() as conn:
        rows = {tid: repo.get(conn, store, tid) for tid in (parent_id, child_id)}
        missing = [tid for tid, row in rows.items() if row is None]
        if missing:
            raise ValueError(f"unknown task(s): {', '.join(missing)}")
        child, parent = (rows[child_id], rows[parent_id])
        if child['status'] == 'running' and (expected_child_run_id is None or child['current_run_id'] != expected_child_run_id):
            raise ValueError(f'cannot link {parent_id} -> {child_id}: child is already running')
        if _would_cycle(conn, store, parent_id, child_id):
            raise ValueError(f'linking {parent_id} -> {child_id} would create a cycle')
        repo.link(conn, store, parent_id, child_id)
        gated = child['status'] == 'ready' and parent['status'] not in {'done', 'archived'}
        if gated:
            repo.task_update(conn, store, child_id, status='todo')
            repo.event(conn, store, child_id, 'dependency_wait', {'reason': 'parent_not_done', 'demoted': True, 'parent': parent_id})
        repo.event(conn, store, child_id, 'linked', {'parent': parent_id, 'child': child_id})
        from hermes_db.domains.kanban.postgres.notify import inherit
        inherit(conn, store, child_id, (parent_id,))
        return store.command_result(conn, gated)

def unlink_tasks(store, parent_id, child_id):
    with store.write() as conn:
        removed = conn.execute(delete(links).where(repo.scope(links, store), links.c.parent_id == encode_text(parent_id), links.c.child_id == encode_text(child_id))).rowcount > 0
        if removed:
            repo.event(conn, store, child_id, 'unlinked', {'parent': parent_id, 'child': child_id})
    if removed:
        recompute_ready(store)
    return removed

def task_graph_contexts(store, task_ids):
    ids = list(dict.fromkeys(str(task_id) for task_id in task_ids if task_id))
    contexts = {task_id: {'parents': [], 'children': []} for task_id in ids}
    with store.read() as conn:
        for task_id in ids:
            for bucket, parents in (('parents', True), ('children', False)):
                for linked in repo.linked_ids(conn, store, task_id, parents=parents):
                    row = repo.require_task(conn, store, linked)
                    contexts[task_id][bucket].append({key: row[key] for key in ('id', 'title', 'status')})
    return contexts

def task_graph_context(store, task_id):
    return task_graph_contexts(store, [task_id])[task_id]

def _promote(conn, store, row, failure_limit):
    task_id = row['id']
    history = repo.history(conn, store, task_id)
    if row['status'] == 'blocked':
        limit = int(row['max_retries']) if row['max_retries'] is not None else int(failure_limit)
        if repo.blocked_is_sticky(history) or int(row['consecutive_failures'] or 0) >= limit:
            return False
    if _unsatisfied(conn, store, task_id):
        return False
    status = repo.resume_status(history)
    repo.task_update(conn, store, task_id, status=status)
    repo.event(conn, store, task_id, 'promoted', {'status': status} if status != 'ready' else None)
    return True

def recompute_ready(store, failure_limit=None):
    from hermes_db.domains.kanban.rules import DEFAULT_FAILURE_LIMIT
    limit = DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit
    with store.write() as conn:
        rows = conn.execute(select(tasks).where(repo.scope(tasks, store), tasks.c.status.in_([b'todo', b'blocked']))).mappings().all()
        return store.command_result(conn, sum(_promote(conn, store, repo.decode_task(row), limit) for row in rows))

def specify_triage_task(store, task_id, *, title=None, body=None, assignee=None, author=None):
    from hermes_db.domains.kanban.rules import _canonical_assignee
    if title is not None and (not title.strip()):
        raise ValueError('title cannot be blank')
    assignee = _canonical_assignee(assignee)
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row['status'] != 'triage':
            return False
        changed = {}
        for key, value in (('title', title.strip() if title is not None else None), ('body', body), ('assignee', assignee)):
            if value is not None and value != (row[key] or (None if key == 'assignee' else '')):
                changed[key] = value
        repo.task_update(conn, store, task_id, status='todo', **changed)
        if changed and author and author.strip():
            repo.comment(conn, store, task_id, author.strip(), 'Specified — updated ' + ', '.join(changed) + ' and promoted to todo.', int(time.time()))
        repo.event(conn, store, task_id, 'specified', {'changed_fields': list(changed)} if changed else None)
    recompute_ready(store)
    return True

def _decomposed_child(conn, store, root, child, author, now, path_key):

    from hermes_db.domains.kanban.postgres import workspaces
    root_kind = root['workspace_kind'] or 'scratch'
    kind = child.get('workspace_kind') or root_kind
    path = child.get('workspace_path')
    if not path:
        path = root['workspace_path'] if kind == root_kind and kind != 'worktree' else None
        path_key = workspaces.key_for_task(conn, store, root['id']) if path else None
    body = child.get('body')
    task_id = _storage_shared_1._new_task_id()
    values = dict(id=task_id, title=child['title'].strip(), body=body if isinstance(body, str) else None, assignee=_storage_shared_1._canonical_assignee(child.get('assignee')), status='todo', workspace_kind=kind, workspace_path=path, tenant=root['tenant'], created_at=now, created_by=author or 'decomposer', session_id=root['session_id'])
    conn.execute(tasks.insert().values(**repo.owner(store), **repo.encode_task(values)))
    workspaces.register(conn, store, task_id, path_key)
    repo.event(conn, store, task_id, 'created', {'by': author or 'decomposer', 'from_decompose_of': root['id']})
    from hermes_db.domains.kanban.postgres.notify import inherit
    inherit(conn, store, task_id, (root['id'],), created_at=now)
    return task_id

def decompose_triage_task(store, task_id, *, root_assignee, children, author=None, auto_promote=True):
    from hermes_db.domains.kanban.rules import _canonical_assignee
    from hermes_db.domains.kanban.rules import _validate_children_graph
    if not children:
        return None
    root_assignee = _canonical_assignee(root_assignee)
    _validate_children_graph(children)
    from hermes_db.domains.kanban.postgres.workspaces import canonical_path
    path_keys = [canonical_path(child.get('workspace_path')) for child in children]
    with store.write() as conn:
        root = repo.get(conn, store, task_id)
        if root is None or root['status'] != 'triage' or any(row['kind'] == 'decomposed' for row in repo.history(conn, store, task_id)):
            return None
        now = int(time.time())
        ids = [_decomposed_child(conn, store, root, child, author, now, path_keys[index]) for index, child in enumerate(children)]
        for idx, child in enumerate(children):
            for parent_idx in child.get('parents') or []:
                repo.link(conn, store, ids[parent_idx], ids[idx])
                repo.event(conn, store, ids[idx], 'linked', {'parent': ids[parent_idx], 'child': ids[idx]})
        for child_id in ids:
            repo.link(conn, store, child_id, task_id)
        values = {'status': 'todo'}
        if root_assignee is not None:
            values['assignee'] = root_assignee
        repo.task_update(conn, store, task_id, **values)
        if author and author.strip():
            repo.comment(conn, store, task_id, author.strip(), 'Decomposed into ' + ', '.join(ids) + '. Root will wake when all children complete.', now)
        repo.event(conn, store, task_id, 'decomposed', {'child_ids': ids, 'root_assignee': root_assignee})
    if auto_promote:
        recompute_ready(store)
    return ids

def _descendants(conn, store, task_id):
    seen, pending = (set(), list(repo.linked_ids(conn, store, task_id, parents=False)))
    while pending:
        child = pending.pop()
        if child not in seen:
            seen.add(child)
            pending.extend(repo.linked_ids(conn, store, child, parents=False))
    return sorted(seen)

def invalidate(conn, store, task_id, *, author):
    invalidated, terminations = ([], [])
    now = int(time.time())
    for child_id in _descendants(conn, store, task_id):
        row = repo.require_task(conn, store, child_id)
        previous = row['status']
        if previous not in {'ready', 'review', 'running', 'done'}:
            continue
        resume, run_id = ('ready', None)
        if previous == 'review':
            resume = 'review'
        elif previous == 'running':
            resume = run_repo.retry_status(conn, store, child_id, row['current_run_id'])
            terminations.append((row['worker_pid'], row['claim_lock'], row['worker_started_at']))
            run_id = run_repo.close_run(conn, store, row, outcome='reclaimed', status='todo', summary=f'ancestor {task_id} reopened')
        repo.task_update(conn, store, child_id, status='todo', completed_at=None, claim_lock=None, claim_expires=None, worker_pid=None, worker_started_at=None, current_run_id=None, consecutive_failures=0)
        entry = dict(id=child_id, prior_status=previous, new_status='todo', resume_status=resume)
        repo.event(conn, store, child_id, 'descendant_invalidated', {'ancestor': task_id, **{key: value for key, value in entry.items() if key != 'id'}}, run_id)
        repo.event(conn, store, child_id, 'status', {'status': 'todo', 'reason': 'ancestor_reopened', 'parent': task_id, 'previous_status': previous, 'resume_status': resume}, run_id)
        repo.comment(conn, store, child_id, author, f"Invalidated: ancestor {task_id} was reopened; retracted from '{previous}' to 'todo' (will resume via '{resume}').", now)
        invalidated.append(entry)
    return {'invalidated': invalidated, 'terminations': terminations}

def terminate(store, result):

    for pid, lock, birth in result['terminations']:
        store.processes.terminate_reclaimed_worker(pid, lock, started_at=birth)

def invalidate_descendants_for_parent_reopen(store, task_id, *, author):
    with store.write() as conn:
        result = invalidate(conn, store, task_id, author=author)
    terminate(store, result)
    return result
