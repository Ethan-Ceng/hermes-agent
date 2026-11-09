"""Scoped project records and short fenced operations; public DTO definitions retain their existing owner."""
import secrets
from hermes_db.domains.projects.rules import SLUG_RE, normalize_slug, slugify, normalize_path, primary_path_key
from sqlalchemy import and_, select, delete, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.projects import projects, project_folders, project_meta as meta, project_locks as locks, discovered_repos as repo_cache
from hermes_db.core.values import decode_text, encode_text
from contextlib import contextmanager
import os
EXACT_FIELDS = ('id', 'name', 'description', 'icon', 'color', 'board_slug', 'primary_path')

def _scoped(table, scope):
    return table.c.store_id == scope.require_store_id()

def _project_key(scope, project_id):
    return and_(_scoped(projects, scope), projects.c.id == encode_text(project_id))

def _folder_key(scope, project_id, path=None):
    key = and_(_scoped(project_folders, scope), project_folders.c.project_id == encode_text(project_id))
    return key if path is None else and_(key, project_folders.c.path == encode_text(path))

def _lock_store(conn, scope):
    conn.execute(insert(locks).values(store_id=scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks.c.store_id).where(_scoped(locks, scope)).with_for_update()).one()

def _load(conn, store, row):
    scope = store.scope
    if row is None:
        return None
    values = {key: row[key] for key in ('slug', 'created_at', 'archived')}
    values.update({key: decode_text(row[key]) for key in EXACT_FIELDS})
    found = conn.execute(select(project_folders).where(_scoped(project_folders, scope), project_folders.c.project_id == row['id']).order_by(project_folders.c.is_primary.desc(), project_folders.c.added_at)).mappings()
    values['folders'] = [store.folder_value(decode_text(item['path']), decode_text(item['label']), bool(item['is_primary']), item['added_at']) for item in found]
    values['archived'] = bool(values['archived'])
    return store.project_value(**values)

def _get(conn, store, id_or_slug):
    scope = store.scope
    row = conn.execute(select(projects).where(_project_key(scope, id_or_slug))).mappings().one_or_none()
    slug = str(id_or_slug).lower()
    if row is None and SLUG_RE.fullmatch(slug):
        row = conn.execute(select(projects).where(_scoped(projects, scope), projects.c.slug == slug)).mappings().one_or_none()
    return _load(conn, store, row)

def _listing(conn, store, include_archived=False):
    scope = store.scope
    query = select(projects).where(_scoped(projects, scope))
    if not include_archived:
        query = query.where(projects.c.archived == 0)
    return [_load(conn, store, row) for row in conn.execute(query.order_by(projects.c.created_at)).mappings()]

def _unique_slug(conn, scope, candidate):
    count, slug = (1, candidate)
    while conn.scalar(select(projects.c.slug).where(_scoped(projects, scope), projects.c.slug == slug)) is not None:
        count += 1
        slug = candidate[:64 - len(f'-{count}')].rstrip('-_') + f'-{count}'
    return slug

def _read_meta(conn, scope, key):
    return decode_text(conn.scalar(select(meta.c.value).where(_scoped(meta, scope), meta.c.key == key)))

def _save_meta(conn, scope, key, value):
    query = insert(meta).values(store_id=scope.require_store_id(), key=key, value=encode_text(value))
    conn.execute(query.on_conflict_do_update(index_elements=list(meta.primary_key.columns), set_={'value': query.excluded.value}))

@contextmanager
def _write(store):
    with store.write() as conn:
        _lock_store(conn, store.scope)
        yield conn

def _primary(conn, scope, project_id, path):
    conn.execute(update(project_folders).where(_folder_key(scope, project_id)).values(is_primary=0))
    conn.execute(update(project_folders).where(_folder_key(scope, project_id, path)).values(is_primary=1))
    conn.execute(update(projects).where(_project_key(scope, project_id)).values(primary_path=encode_text(path)))

def _find_primary(conn, store, path, include_archived=False):
    key = primary_path_key(path)
    for project in _listing(conn, store, include_archived):
        primary = project.primary_path or next((folder.path for folder in project.folders if folder.is_primary), project.folders[0].path if project.folders else None)
        if primary and primary_path_key(primary) == key:
            return project
    return None

def find_by_primary_path(store, path, *, include_archived=False):
    with store.read() as conn:
        return _find_primary(conn, store, path, include_archived)

def create_project(store, *, name, slug=None, folders=None, primary_path=None, description=None, icon=None, color=None, board_slug=None, allow_duplicate_path=False):
    name = str(name or '').strip()
    if not name:
        raise ValueError('project name must not be empty')
    candidate = normalize_slug(slug) if slug else slugify(name)
    project_id = 'p_' + secrets.token_hex(4)
    now = store.now()
    paths = list(dict.fromkeys(path for path in map(normalize_path, folders or []) if path))
    primary = normalize_path(primary_path) if primary_path else None
    if primary and primary not in paths:
        paths.insert(0, primary)
    primary = primary or (paths[0] if paths else None)
    values = {'id': project_id, 'name': name, 'description': description, 'icon': icon, 'color': color, 'board_slug': normalize_slug(board_slug) if board_slug else None, 'primary_path': primary}
    with _write(store) as conn:
        existing = _find_primary(conn, store, primary) if primary and (not allow_duplicate_path) else None
        if existing is not None:
            raise ValueError(f"folder already belongs to project '{existing.slug}' ({existing.id}); switch to it instead of creating a duplicate")
        conn.execute(projects.insert().values(store_id=store.scope.require_store_id(), slug=_unique_slug(conn, store.scope, candidate), created_at=now, **{key: encode_text(value) for key, value in values.items()}))
        if paths:
            conn.execute(project_folders.insert(), [{'store_id': store.scope.require_store_id(), 'project_id': encode_text(project_id), 'path': encode_text(path), 'is_primary': int(path == primary), 'added_at': now} for path in paths])
    return project_id

def list_projects(store, *, include_archived=False):
    with store.read() as conn:
        return _listing(conn, store, include_archived)

def get_project(store, id_or_slug):
    with store.read() as conn:
        return _get(conn, store, id_or_slug)

def update_project(store, project_id, *, name=None, description=None, icon=None, color=None, board_slug=None):
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValueError('project name must not be empty')
    if board_slug is not None:
        board_slug = normalize_slug(board_slug) if board_slug.strip() else ''
    values = {key: encode_text(value) for key, given, value in (('name', name, name), ('description', description, description), ('icon', icon, icon or None), ('color', color, color or None), ('board_slug', board_slug, board_slug or None)) if given is not None}
    if not values:
        return False
    with _write(store) as conn:
        return conn.execute(update(projects).where(_project_key(store.scope, project_id)).values(**values)).rowcount > 0

def add_folder(store, project_id, path, *, label=None, is_primary=False):
    path = normalize_path(path)
    with _write(store) as conn:
        if _get(conn, store, project_id) is None:
            raise ValueError(f'no such project: {project_id}')
        conn.execute(insert(project_folders).values(store_id=store.scope.require_store_id(), project_id=encode_text(project_id), path=encode_text(path), label=encode_text(label), is_primary=0, added_at=store.now()).on_conflict_do_nothing())
        if label is not None:
            conn.execute(update(project_folders).where(_folder_key(store.scope, project_id, path)).values(label=encode_text(label)))
        has_primary = conn.scalar(select(project_folders.c.path).where(_folder_key(store.scope, project_id), project_folders.c.is_primary == 1))
        if is_primary or has_primary is None:
            _primary(conn, store.scope, project_id, path)
    return path

def remove_folder(store, project_id, path):
    path = normalize_path(path)
    with _write(store) as conn:
        was_primary = conn.scalar(select(project_folders.c.is_primary).where(_folder_key(store.scope, project_id, path)))
        count = conn.execute(delete(project_folders).where(_folder_key(store.scope, project_id, path))).rowcount
        if was_primary:
            next_path = decode_text(conn.scalar(select(project_folders.c.path).where(_folder_key(store.scope, project_id)).order_by(project_folders.c.added_at).limit(1)))
            if next_path:
                _primary(conn, store.scope, project_id, next_path)
            else:
                conn.execute(update(projects).where(_project_key(store.scope, project_id)).values(primary_path=None))
    return count > 0

def set_primary(store, project_id, path):
    path = normalize_path(path)
    with _write(store) as conn:
        if conn.scalar(select(project_folders.c.path).where(_folder_key(store.scope, project_id, path))) is None:
            return False
        _primary(conn, store.scope, project_id, path)
    return True

def _archive(store, project_id, value):
    with _write(store) as conn:
        return conn.execute(update(projects).where(_project_key(store.scope, project_id)).values(archived=value)).rowcount > 0

def archive_project(store, project_id):
    return _archive(store, project_id, 1)

def restore_project(store, project_id):
    return _archive(store, project_id, 0)

def delete_project(store, project_id):
    with _write(store) as conn:
        return conn.execute(delete(projects).where(_project_key(store.scope, project_id))).rowcount > 0

def set_active(store, project_id):
    with _write(store) as conn:
        if project_id is None:
            conn.execute(delete(meta).where(_scoped(meta, store.scope), meta.c.key == 'active_id'))
        else:
            _save_meta(conn, store.scope, 'active_id', project_id)

def _get_meta(store, key):
    with store.read() as conn:
        return _read_meta(conn, store.scope, key)

def get_active_id(store):
    return _get_meta(store, 'active_id')

def get_discovery_policy_key(store):
    return _get_meta(store, 'repo_discovery_policy')

def _clear_repos(conn, scope, clear, policy_key):
    if clear:
        conn.execute(delete(repo_cache).where(_scoped(repo_cache, scope)))
    if policy_key is not None:
        _save_meta(conn, scope, 'repo_discovery_policy', policy_key)

def reconcile_discovered_repos_policy(store, policy_key, *, preserve_unversioned=False):
    with _write(store) as conn:
        current = _read_meta(conn, store.scope, 'repo_discovery_policy')
        if current == policy_key:
            return False
        cleared = current is not None or not preserve_unversioned
        _clear_repos(conn, store.scope, cleared, policy_key)
        return cleared

def clear_discovered_repos(store, *, policy_key=None):
    with _write(store) as conn:
        _clear_repos(conn, store.scope, True, policy_key)

def record_discovered_repos(store, repos, *, replace=False, policy_key=None):
    rows = [{'store_id': store.scope.require_store_id(), 'root': encode_text(root), 'label': encode_text(label or os.path.basename(root) or root), 'last_seen': store.now()} for root, label in ((normalize_path(root), label) for root, label in repos) if root]
    with _write(store) as conn:
        _clear_repos(conn, store.scope, replace, policy_key)
        for row in rows:
            query = insert(repo_cache).values(**row)
            conn.execute(query.on_conflict_do_update(index_elements=list(repo_cache.primary_key.columns), set_={'label': query.excluded.label, 'last_seen': query.excluded.last_seen}))
    return len(rows)

def list_discovered_repos(store):
    with store.read() as conn:
        return [{'root': decode_text(row['root']), 'label': decode_text(row['label']), 'last_seen': row['last_seen']} for row in conn.execute(select(repo_cache).where(_scoped(repo_cache, store.scope)).order_by(repo_cache.c.last_seen.desc())).mappings()]

def project_for_path(store, path, *, include_archived=False):
    if not str(path or '').strip():
        return None
    target = normalize_path(path)
    with store.read() as conn:
        owners = [(folder.path, project) for project in _listing(conn, store, include_archived) for folder in project.folders if target == folder.path or any(target.startswith(folder.path.rstrip('/\\') + separator) for separator in (os.sep, '/'))]
        return max(owners, key=lambda pair: len(pair[0]))[1] if owners else None
