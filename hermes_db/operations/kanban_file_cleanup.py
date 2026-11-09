"""Only unreferenced retired generation directories are removed, outside SQL."""

from pathlib import Path
import shutil
from sqlalchemy import and_, select

from hermes_db.errors import StorageConfigurationError
from hermes_db.operations.kanban_file_jobs import ROOT_FIELDS, lock_files, set_job_state, under_root
from hermes_db.tables.kanban import tasks
from hermes_db.tables.kanban_artifacts import attachments
from hermes_db.tables.kanban_workspaces import references
from hermes_db.core.values import decode_text


def _references(conn, store, roots):
    joined = and_(tasks.c.store_id == references.c.store_id, tasks.c.board_id == references.c.board_id,
                  tasks.c.id == references.c.task_id)
    live = list(conn.scalars(select(references.c.path_key).join(tasks, joined).where(
        references.c.store_id == store.scope.require_store_id(), tasks.c.status.not_in([b"done", b"archived", b"failed", b"cancelled"]))))
    blobs = list(conn.scalars(select(attachments.c.path_key).where(attachments.c.store_id == store.scope.require_store_id())))
    unresolved = conn.scalar(select(tasks.c.id).outerjoin(references, joined).where(
        tasks.c.store_id == store.scope.require_store_id(), tasks.c.workspace_path.is_not(None),
        tasks.c.status.not_in([b"done", b"archived", b"failed", b"cancelled"]), references.c.task_id.is_(None)).limit(1))
    if unresolved is not None:
        return "unresolved workspace paths require reconciliation"
    if any(value is None for value in blobs):
        return "unresolved attachment paths require reconciliation"
    if any(under_root(decode_text(value), root) for value in [*live, *blobs] for root in roots):
        return "other Board tasks or attachments still reference this content"
    return None


def _remove_directory(path, *, board_id=None, parent=None):
    path = Path(path)
    resolved = path.resolve()
    if (not path.is_absolute() or resolved != path or path == Path(path.anchor)
            or (board_id is not None and board_id not in path.parts)
            or (parent is not None and (not resolved.is_relative_to(parent.resolve()) or resolved == parent.resolve()))):
        raise StorageConfigurationError("Board cleanup path escaped or redirected its captured directory")
    if path.exists():
        if not path.is_dir():
            raise StorageConfigurationError("Board cleanup expected a directory; preserve the unexpected file")
        shutil.rmtree(path)


def delete_files(store, row):
    if row["state"] == "done":
        return {"new_path": "", "files_pending": False}
    if row["state"] == "pending":
        home = Path(row["owner_home"])
        _remove_directory(home / "kanban" / "boards" / row["slug"], parent=home / "kanban" / "boards")
        _remove_directory(home / "kanban" / "boards" / "_archived" / f"{row['slug']}-{row['board_id']}",
                          parent=home / "kanban" / "boards" / "_archived")
        set_job_state(store, row["board_id"], "content_pending")
    roots = sorted({row[name] for name in ROOT_FIELDS}, key=lambda value: len(Path(value).parts))
    with store.write() as conn:
        lock_files(conn, store)
        reason = _references(conn, store, roots)
    if reason is not None:
        return {"new_path": "", "files_pending": True, "files_pending_reason": reason}
    selected = []
    for root in roots:
        if not any(Path(root).is_relative_to(Path(previous)) for previous in selected):
            selected.append(root)
    for root in selected:
        _remove_directory(root, board_id=row["board_id"])
    set_job_state(store, row["board_id"], "done")
    return {"new_path": "", "files_pending": False}
