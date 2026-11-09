"""Scoped detached project records; no implicit transactions."""

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.projects import projects, project_folders as folders, project_meta as meta, project_locks as locks
from hermes_db.core.values import decode_text, encode_text

EXACT_FIELDS = ("id", "name", "description", "icon", "color", "board_slug", "primary_path")


def scoped(table, scope):
    return table.c.store_id == scope.require_store_id()


def project_key(scope, project_id):
    return and_(scoped(projects, scope), projects.c.id == encode_text(project_id))


def folder_key(scope, project_id, path=None):
    key = and_(scoped(folders, scope), folders.c.project_id == encode_text(project_id))
    return key if path is None else and_(key, folders.c.path == encode_text(path))


def lock_store(conn, scope):
    conn.execute(insert(locks).values(store_id=scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks.c.store_id).where(scoped(locks, scope)).with_for_update()).one()


def load(conn, scope, row):
    from hermes_cli.projects_db import Project, ProjectFolder
    if row is None:
        return None
    values = {key: row[key] for key in ("slug", "created_at", "archived")}
    values.update({key: decode_text(row[key]) for key in EXACT_FIELDS})
    found = conn.execute(select(folders).where(scoped(folders, scope), folders.c.project_id == row["id"])
                         .order_by(folders.c.is_primary.desc(), folders.c.added_at)).mappings()
    values["folders"] = [ProjectFolder(decode_text(item["path"]), decode_text(item["label"]),
                                       bool(item["is_primary"]), item["added_at"]) for item in found]
    values["archived"] = bool(values["archived"])
    return Project(**values)


def get(conn, scope, id_or_slug):
    from hermes_cli.projects_db import _SLUG_RE
    row = conn.execute(select(projects).where(project_key(scope, id_or_slug))).mappings().one_or_none()
    slug = str(id_or_slug).lower()
    if row is None and _SLUG_RE.fullmatch(slug):
        row = conn.execute(select(projects).where(scoped(projects, scope), projects.c.slug == slug)).mappings().one_or_none()
    return load(conn, scope, row)


def listing(conn, scope, include_archived=False):
    query = select(projects).where(scoped(projects, scope))
    if not include_archived:
        query = query.where(projects.c.archived == 0)
    return [load(conn, scope, row) for row in conn.execute(query.order_by(projects.c.created_at)).mappings()]


def unique_slug(conn, scope, candidate):
    count, slug = 1, candidate
    while conn.scalar(select(projects.c.slug).where(scoped(projects, scope), projects.c.slug == slug)) is not None:
        count += 1
        slug = candidate[:64 - len(f"-{count}")].rstrip("-_") + f"-{count}"
    return slug


def read_meta(conn, scope, key):
    return decode_text(conn.scalar(select(meta.c.value).where(scoped(meta, scope), meta.c.key == key)))


def save_meta(conn, scope, key, value):
    query = insert(meta).values(store_id=scope.require_store_id(), key=key, value=encode_text(value))
    conn.execute(query.on_conflict_do_update(index_elements=list(meta.primary_key.columns), set_={"value": query.excluded.value}))
