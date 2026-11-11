"""Kanban logical archive schemas, query snapshots and atomic graph import."""
import time
from sqlalchemy import select, LargeBinary, update
from hermes_db.domains.kanban.postgres import repository as repo, catalog as boards, files
from hermes_db.tables.kanban import tasks, links, comments, events, runs, kanban_boards
from hermes_db.tables.kanban_artifacts import attachments
from hermes_db.tables.kanban_file_jobs import file_jobs
from hermes_db.domains.kanban.api import BoardResource
from hermes_db.domains.kanban.postgres.files import job_key, lock_files
from hermes_db.errors import StorageConfigurationError
from hermes_db.core.values import encode_text
FORMAT_VERSION = 2

TABLES = {'tasks': tasks, 'task_links': links, 'task_comments': comments, 'task_events': events, 'task_runs': runs, 'task_attachments': attachments}

LOCAL_TASK_FIELDS = ('claim_lock', 'claim_expires', 'worker_pid', 'worker_started_at', 'current_run_id', 'last_heartbeat_at', 'session_id', 'project_id', 'last_failure_error', 'workspace_path', 'branch_name')



def snapshot(store):
    result = {}
    with store.read() as conn:
        for name, table in TABLES.items():
            columns = [column for column in table.columns if column.name not in {'store_id', 'board_id', 'path_key'}]
            result[name] = [repo.decode_record(row) for row in conn.execute(select(*columns).where(repo.scope(table, store))).mappings()]
    return result


def scrub_runtime(tables):
    for task in tables['tasks']:
        for field in LOCAL_TASK_FIELDS:
            task[field] = None
        task['consecutive_failures'] = 0
        if task['status'] == 'running':
            task['status'] = 'ready'
    for run in tables['task_runs']:
        for field in ('claim_lock', 'claim_expires', 'worker_pid', 'worker_started_at', 'last_heartbeat_at'):
            run[field] = None
        if run['status'] == 'running':
            run.update(status='released', outcome=run['outcome'] or 'reclaimed', ended_at=run['ended_at'] or int(time.time()))


def insert_import_row(conn, store, table, row, *, returning=False):
    values = {name: encode_text(value) if isinstance(table.c[name].type, LargeBinary) else value for name, value in row.items()}
    statement = table.insert().values(**repo.owner(store), **values)
    return conn.scalar(statement.returning(table.c.id)) if returning else conn.execute(statement)


def _insert_rows(conn, store, tables, parked):
    for row in tables['tasks']:
        insert_import_row(conn, store, TABLES['tasks'], row)
    run_ids = {}
    for original in sorted(tables['task_runs'], key=lambda row: row['id']):
        row = dict(original)
        old = row.pop('id')
        run_ids[old] = insert_import_row(conn, store, TABLES['task_runs'], row, returning=True)
    for name in ('task_links', 'task_comments', 'task_attachments', 'task_events'):
        for original in sorted(tables[name], key=lambda row: row.get('id', 0)):
            row = {name: value for name, value in original.items() if name != 'id'}
            if name == 'task_events' and row['run_id'] is not None:
                if row['run_id'] not in run_ids:
                    raise ValueError('Board archive event references an unknown run')
                row['run_id'] = run_ids[row['run_id']]
            insert_import_row(conn, store, TABLES[name], row)
    for row in tables['tasks']:
        repo.event(conn, store, row['id'], 'imported', {'board': store.slug, 'parked': row['id'] in parked})


def _target_slug(conn, resource, requested):
    stem = requested[:58].rstrip('-_') or 'board'
    candidate, suffix = (requested, 2)
    while True:
        pending = conn.scalar(select(file_jobs.c.board_id).where(file_jobs.c.store_id == resource.scope.require_store_id(), file_jobs.c.slug == candidate, file_jobs.c.state == 'pending').limit(1))
        if candidate != 'default' and boards._lookup(conn, resource, candidate) is None and (pending is None):
            return candidate
        candidate, suffix = (f'{stem}-{suffix}', suffix + 1)


def _commit_graph(resource, requested, board_id, stage, tables, fields, parked):
    with resource.write() as conn:
        files.lock_files(conn, resource)
        boards._registry_lock(conn, resource)
        target = _target_slug(conn, resource, requested)
        boards._save(conn, resource, target, None, True, new_board_id=board_id)
        board = BoardResource(resource, board_id, target)
        try:
            conn.execute(file_jobs.insert().values(store_id=resource.scope.require_store_id(), board_id=board_id, slug=target, action='import', state='pending', created_at=int(time.time()), stage_root=encode_text(str(stage)), **{name: encode_text(value) for name, value in fields.items()}))
            _insert_rows(conn, board, tables, parked)
        finally:
            board.close()
    return target


def _activate(store, row):
    from hermes_db.domains.kanban.postgres.catalog import _registry_lock
    with store.write() as conn:
        lock_files(conn, store)
        _registry_lock(conn, store)
        condition = (kanban_boards.c.store_id == store.scope.require_store_id()) & (kanban_boards.c.board_id == row['board_id'])
        current = conn.execute(select(kanban_boards).where(condition).with_for_update()).mappings().one_or_none()
        if current is None:
            raise StorageConfigurationError('Imported Board generation no longer exists')
        conn.execute(update(kanban_boards).where(condition).values(archived=0))
        conn.execute(update(file_jobs).where(job_key(store, row['board_id'])).values(state='done'))


def _rows(tables):
    from sqlalchemy import BigInteger
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError('Board archive must contain all supported data tables')
    for name, table in TABLES.items():
        columns = {column.name: column for column in table.columns if column.name not in {'store_id', 'board_id', 'path_key'}}
        if not isinstance(tables[name], list):
            raise ValueError('Board archive table must contain rows')
        for row in tables[name]:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError(f'Board archive {name} has unsupported columns')
            for key, column in columns.items():
                value = row[key]
                valid = value is None and column.nullable
                valid = valid or (type(value) is int if isinstance(column.type, BigInteger) else isinstance(value, str))
                if not valid:
                    raise ValueError(f'Board archive {name}.{key} has an invalid value')
        identities = [(row['parent_id'], row['child_id']) if name == 'task_links' else row['id'] for row in tables[name]]
        if len(set(identities)) != len(identities):
            raise ValueError(f'Board archive {name} contains duplicate identities')


def _graph(tables):
    from collections import deque
    from hermes_cli.kanban_workflow import DEFAULT_STATUSES as VALID_STATUSES
    from hermes_db.domains.kanban.rules import VALID_WORKSPACE_KINDS
    tasks = {row['id']: row for row in tables['tasks']}
    incoming = dict.fromkeys(tasks, 0)
    children = {key: [] for key in tasks}
    for row in tasks.values():
        if row['status'] not in VALID_STATUSES or row['workspace_kind'] not in VALID_WORKSPACE_KINDS:
            raise ValueError('Board archive contains an unsupported task status or workspace kind')
    for edge in tables['task_links']:
        parent, child = (edge['parent_id'], edge['child_id'])
        if parent not in tasks or child not in tasks:
            raise ValueError('Board archive dependency references an unknown task')
        incoming[child] += 1
        children[parent].append(child)
    ready = deque((key for key, count in incoming.items() if count == 0))
    visited = 0
    while ready:
        parent = ready.popleft()
        visited += 1
        for child in children[parent]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if visited != len(tasks):
        raise ValueError('Board archive dependency graph contains a cycle')


def clear_import_stage(store, row):
    with store.write() as conn:
        lock_files(conn, store)
        conn.execute(update(file_jobs).where(job_key(store, row['board_id']), file_jobs.c.action == 'import', file_jobs.c.state == 'done').values(stage_root=None))
