"""Named Projects operations; every mutation holds one short store fence."""

from contextlib import contextmanager
import os

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.repositories import projects as repo
from hermes_db.tables.projects import projects, project_folders as folders, project_meta as meta, discovered_repos as repo_cache
from hermes_db.core.values import decode_text, encode_text


@contextmanager
def _write(store):
    with store.write() as conn:
        repo.lock_store(conn, store.scope)
        yield conn


def _primary(conn, scope, project_id, path):
    conn.execute(update(folders).where(repo.folder_key(scope, project_id)).values(is_primary=0))
    conn.execute(update(folders).where(repo.folder_key(scope, project_id, path)).values(is_primary=1))
    conn.execute(update(projects).where(repo.project_key(scope, project_id)).values(primary_path=encode_text(path)))


def _find_primary(conn, scope, path, include_archived=False):
    from hermes_cli.projects_db import _primary_path_key
    key = _primary_path_key(path)
    for project in repo.listing(conn, scope, include_archived):
        primary = project.primary_path or next((folder.path for folder in project.folders if folder.is_primary),
                                               project.folders[0].path if project.folders else None)
        if primary and _primary_path_key(primary) == key:
            return project
    return None


def find_by_primary_path(store, path, *, include_archived=False):
    with store.read() as conn:
        return _find_primary(conn, store.scope, path, include_archived)


def create_project(store, *, name, slug=None, folders=None, primary_path=None, description=None,
                   icon=None, color=None, board_slug=None, allow_duplicate_path=False):
    from hermes_cli import projects_db as pdb
    name = str(name or "").strip()
    if not name:
        raise ValueError("project name must not be empty")
    candidate = pdb.normalize_slug(slug) if slug else pdb._slugify(name)
    project_id = "p_" + pdb.secrets.token_hex(4)
    now = pdb._now()
    paths = list(dict.fromkeys(path for path in map(pdb._normalize_path, folders or []) if path))
    primary = pdb._normalize_path(primary_path) if primary_path else None
    if primary and primary not in paths:
        paths.insert(0, primary)
    primary = primary or (paths[0] if paths else None)
    values = {"id": project_id, "name": name, "description": description, "icon": icon, "color": color,
              "board_slug": pdb.normalize_slug(board_slug) if board_slug else None, "primary_path": primary}
    with _write(store) as conn:
        existing = _find_primary(conn, store.scope, primary) if primary and not allow_duplicate_path else None
        if existing is not None:
            raise ValueError(f"folder already belongs to project '{existing.slug}' ({existing.id}); switch to it instead of creating a duplicate")
        conn.execute(projects.insert().values(store_id=store.scope.require_store_id(),
            slug=repo.unique_slug(conn, store.scope, candidate), created_at=now,
            **{key: encode_text(value) for key, value in values.items()}))
        if paths:
            conn.execute(repo.folders.insert(), [{"store_id": store.scope.require_store_id(), "project_id": encode_text(project_id),
                "path": encode_text(path), "is_primary": int(path == primary), "added_at": now} for path in paths])
    return project_id


def list_projects(store, *, include_archived=False):
    with store.read() as conn:
        return repo.listing(conn, store.scope, include_archived)


def get_project(store, id_or_slug):
    with store.read() as conn:
        return repo.get(conn, store.scope, id_or_slug)


def update_project(store, project_id, *, name=None, description=None, icon=None, color=None, board_slug=None):
    from hermes_cli.projects_db import normalize_slug
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValueError("project name must not be empty")
    if board_slug is not None:
        board_slug = normalize_slug(board_slug) if board_slug.strip() else ""
    values = {key: encode_text(value) for key, given, value in (
        ("name", name, name), ("description", description, description), ("icon", icon, icon or None),
        ("color", color, color or None), ("board_slug", board_slug, board_slug or None)) if given is not None}
    if not values:
        return False
    with _write(store) as conn:
        return conn.execute(update(projects).where(repo.project_key(store.scope, project_id)).values(**values)).rowcount > 0


def add_folder(store, project_id, path, *, label=None, is_primary=False):
    from hermes_cli.projects_db import _normalize_path, _now
    path = _normalize_path(path)
    with _write(store) as conn:
        if repo.get(conn, store.scope, project_id) is None:
            raise ValueError(f"no such project: {project_id}")
        conn.execute(insert(folders).values(store_id=store.scope.require_store_id(), project_id=encode_text(project_id),
            path=encode_text(path), label=encode_text(label), is_primary=0, added_at=_now()).on_conflict_do_nothing())
        if label is not None:
            conn.execute(update(folders).where(repo.folder_key(store.scope, project_id, path)).values(label=encode_text(label)))
        has_primary = conn.scalar(select(folders.c.path).where(repo.folder_key(store.scope, project_id), folders.c.is_primary == 1))
        if is_primary or has_primary is None:
            _primary(conn, store.scope, project_id, path)
    return path


def remove_folder(store, project_id, path):
    from hermes_cli.projects_db import _normalize_path
    path = _normalize_path(path)
    with _write(store) as conn:
        was_primary = conn.scalar(select(folders.c.is_primary).where(repo.folder_key(store.scope, project_id, path)))
        count = conn.execute(delete(folders).where(repo.folder_key(store.scope, project_id, path))).rowcount
        if was_primary:
            next_path = decode_text(conn.scalar(select(folders.c.path).where(repo.folder_key(store.scope, project_id))
                                                .order_by(folders.c.added_at).limit(1)))
            if next_path:
                _primary(conn, store.scope, project_id, next_path)
            else:
                conn.execute(update(projects).where(repo.project_key(store.scope, project_id)).values(primary_path=None))
    return count > 0


def set_primary(store, project_id, path):
    from hermes_cli.projects_db import _normalize_path
    path = _normalize_path(path)
    with _write(store) as conn:
        if conn.scalar(select(folders.c.path).where(repo.folder_key(store.scope, project_id, path))) is None:
            return False
        _primary(conn, store.scope, project_id, path)
    return True


def _archive(store, project_id, value):
    with _write(store) as conn:
        return conn.execute(update(projects).where(repo.project_key(store.scope, project_id)).values(archived=value)).rowcount > 0


def archive_project(store, project_id):
    return _archive(store, project_id, 1)


def restore_project(store, project_id):
    return _archive(store, project_id, 0)


def delete_project(store, project_id):
    with _write(store) as conn:
        return conn.execute(delete(projects).where(repo.project_key(store.scope, project_id))).rowcount > 0


def set_active(store, project_id):
    with _write(store) as conn:
        if project_id is None:
            conn.execute(delete(meta).where(repo.scoped(meta, store.scope), meta.c.key == "active_id"))
        else:
            repo.save_meta(conn, store.scope, "active_id", project_id)


def _get_meta(store, key):
    with store.read() as conn:
        return repo.read_meta(conn, store.scope, key)


def get_active_id(store):
    return _get_meta(store, "active_id")


def get_discovery_policy_key(store):
    return _get_meta(store, "repo_discovery_policy")


def _clear_repos(conn, scope, clear, policy_key):
    if clear:
        conn.execute(delete(repo_cache).where(repo.scoped(repo_cache, scope)))
    if policy_key is not None:
        repo.save_meta(conn, scope, "repo_discovery_policy", policy_key)


def reconcile_discovered_repos_policy(store, policy_key, *, preserve_unversioned=False):
    with _write(store) as conn:
        current = repo.read_meta(conn, store.scope, "repo_discovery_policy")
        if current == policy_key:
            return False
        cleared = current is not None or not preserve_unversioned
        _clear_repos(conn, store.scope, cleared, policy_key)
        return cleared


def clear_discovered_repos(store, *, policy_key=None):
    with _write(store) as conn:
        _clear_repos(conn, store.scope, True, policy_key)


def record_discovered_repos(store, repos, *, replace=False, policy_key=None):
    from hermes_cli.projects_db import _normalize_path, _now
    rows = [{"store_id": store.scope.require_store_id(), "root": encode_text(root),
             "label": encode_text(label or os.path.basename(root) or root), "last_seen": _now()}
            for root, label in ((_normalize_path(root), label) for root, label in repos) if root]
    with _write(store) as conn:
        _clear_repos(conn, store.scope, replace, policy_key)
        for row in rows:
            query = insert(repo_cache).values(**row)
            conn.execute(query.on_conflict_do_update(index_elements=list(repo_cache.primary_key.columns),
                set_={"label": query.excluded.label, "last_seen": query.excluded.last_seen}))
    return len(rows)


def list_discovered_repos(store):
    with store.read() as conn:
        return [{"root": decode_text(row["root"]), "label": decode_text(row["label"]), "last_seen": row["last_seen"]}
                for row in conn.execute(select(repo_cache).where(repo.scoped(repo_cache, store.scope))
                                        .order_by(repo_cache.c.last_seen.desc())).mappings()]


def project_for_path(store, path, *, include_archived=False):
    from hermes_cli.projects_db import _normalize_path
    if not str(path or "").strip():
        return None
    target = _normalize_path(path)
    with store.read() as conn:
        owners = [(folder.path, project) for project in repo.listing(conn, store.scope, include_archived)
                  for folder in project.folders if target == folder.path or any(
                      target.startswith(folder.path.rstrip("/\\") + separator) for separator in (os.sep, "/"))]
        return max(owners, key=lambda pair: len(pair[0]))[1] if owners else None
