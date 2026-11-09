"""Typed local-file references move with a Profile; transcript text stays immutable."""

import json
import os
from pathlib import Path
import unicodedata
from sqlalchemy import select

from hermes_db.errors import StorageConflictError, StorageConfigurationError
from hermes_db.core.values import decode_text, encode_text


def relocate(value, old, new, *, key=False):
    if value is None:
        return None
    text = decode_text(value) if isinstance(value, (bytes, memoryview)) else value
    if key:
        old, new = (os.path.normcase(unicodedata.normalize("NFC", str(path))) for path in (old, new))
    path = Path(text)
    if not path.is_absolute():
        return value
    try:
        changed = str(Path(new) / path.relative_to(old))
    except ValueError:
        return value
    return encode_text(changed) if isinstance(value, (bytes, memoryview)) else changed


def _where(table, row):
    return [column == row[column.name] for column in table.primary_key.columns]


def _columns(conn, resource, table, names, old, new):
    columns = list(dict.fromkeys([*table.primary_key.columns, *(table.c[name] for name in names)]))
    rows = conn.execute(select(*columns).where(table.c.store_id == resource.scope.require_store_id())).mappings().all()
    for row in rows:
        values = {name: relocate(row[name], old, new, key=name == "path_key") for name in names}
        values = {name: value for name, value in values.items() if value != row[name]}
        if values:
            conn.execute(table.update().where(*_where(table, row)).values(**values))


def payload_paths(value, old, new):
    if isinstance(value, list):
        return [payload_paths(item, old, new) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        pointer = key in {"workspace_path", "stored_path", "profile_home", "owner_home"}
        pointer |= key == "home" and "store_id" in value and "target" in value
        pointer |= key == "workspace" and "owner" in value
        if pointer and isinstance(item, str):
            result[key] = relocate(item, old, new)
        elif key == "artifacts" and isinstance(item, list):
            result[key] = [relocate(path, old, new) if isinstance(path, str) else path for path in item]
        elif key in {"kanban_json", "kanban"} and isinstance(item, str):
            result[key] = _json_paths(item, old, new)
        else:
            result[key] = payload_paths(item, old, new)
    return result


def _json_paths(raw, old, new):
    try:
        original = json.loads(decode_text(raw) if isinstance(raw, (bytes, memoryview)) else raw)
    except (TypeError, ValueError):
        return raw  # Historical opaque/invalid metadata is not a relocation authority.
    changed = payload_paths(original, old, new)
    if changed == original:
        return raw
    value = json.dumps(changed, ensure_ascii=True, separators=(",", ":"))
    return encode_text(value) if isinstance(raw, (bytes, memoryview)) else value


def _json_column(conn, resource, table, name, old, new, *, condition=None):
    query = select(table).where(table.c.store_id == resource.scope.require_store_id(), table.c[name].is_not(None))
    if condition is not None:
        query = query.where(condition)
    for row in conn.execute(query).mappings().all():
        changed = _json_paths(row[name], old, new)
        if changed != row[name]:
            conn.execute(table.update().where(*_where(table, row)).values({name: changed}))


def _workspace_keys(conn, resource, old, new):
    from hermes_db.tables.kanban_workspaces import paths, references
    owned = resource.scope.require_store_id()
    rows = conn.execute(select(paths).where(paths.c.store_id == owned).with_for_update()).mappings().all()
    for row in rows:
        if row["cleanup_token"] is not None:
            _require_cleanup_payload(row["cleanup_payload"])
        key = relocate(row["path_key"], old, new, key=True)
        payload = _json_paths(row["cleanup_payload"], old, new) if row["cleanup_payload"] is not None else None
        if key == row["path_key"]:
            if payload != row["cleanup_payload"]:
                conn.execute(paths.update().where(*_where(paths, row)).values(cleanup_payload=payload))
            continue
        if conn.scalar(select(paths.c.path_key).where(paths.c.store_id == owned, paths.c.path_key == key)) is not None:
            raise StorageConflictError("Relocated workspace collides with an existing path; preserve the Profile move journal")
        conn.execute(paths.insert().values(store_id=owned, path_key=key, cleanup_token=row["cleanup_token"], cleanup_payload=payload))
        conn.execute(references.update().where(references.c.store_id == owned, references.c.path_key == row["path_key"]).values(path_key=key))
        conn.execute(paths.delete().where(*_where(paths, row)))


def _require_cleanup_payload(raw):
    try:
        value = json.loads(bytes(raw))
    except (TypeError, ValueError):
        raise StorageConfigurationError("Workspace cleanup intent cannot be relocated safely; preserve the Profile move journal") from None
    if not isinstance(value, dict) or not isinstance(value.get("task"), dict) or not {"board_id", "slug"} <= value.keys():
        raise StorageConfigurationError("Workspace cleanup intent cannot be relocated safely; preserve the Profile move journal")


def reanchor(resource, old, new):
    from hermes_db.domains.sessions.postgres.queries.sessions import lock_store
    from hermes_db.operations.kanban_file_jobs import lock_files
    from hermes_db.tables.conversations import sessions
    from hermes_db.tables.projects import projects, project_folders, discovered_repos
    from hermes_db.tables.cron import cron_incidents
    from hermes_db.tables.kanban import tasks, runs, events
    from hermes_db.tables.kanban_artifacts import attachments, blobs
    from hermes_db.tables.kanban_file_jobs import file_jobs
    from hermes_db.tables.kanban_effects import effects
    from hermes_db.tables.gateway import gateway_routing
    fields = ((sessions, ("cwd", "git_repo_root")), (projects, ("primary_path",)), (project_folders, ("path",)),
        (discovered_repos, ("root",)), (cron_incidents, ("output_file",)), (tasks, ("workspace_path",)),
        (attachments, ("stored_path", "path_key")), (blobs, ("path",)), (effects, ("owner_home",)),
        (file_jobs, ("owner_home", "data_root", "attachments_root", "workspaces_root", "logs_root", "stage_root")))
    with resource.write() as conn:
        lock_files(conn, resource)
        lock_store(conn, resource.scope, exclusive=True)
        for table, names in fields:
            _columns(conn, resource, table, names, old, new)
        _workspace_keys(conn, resource, old, new)
        for table, column in ((runs, "metadata"), (effects, "payload"), (gateway_routing, "entry_json")):
            _json_column(conn, resource, table, column, old, new)
        _json_column(conn, resource, events, "payload", old, new, condition=events.c.kind == encode_text("owner_admitted"))
