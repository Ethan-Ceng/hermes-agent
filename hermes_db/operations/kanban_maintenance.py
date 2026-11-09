"""Replay committed file jobs and terminal-task effects in their captured owning Profile."""

import re
from sqlalchemy import select

from hermes_db.domains.kanban import BoardResource
from hermes_db.domains.kanban_files import board_files
from hermes_db.operations import kanban_file_jobs as files
from hermes_db.tables.kanban import kanban_boards, tasks
from hermes_db.tables.kanban_file_jobs import file_jobs
from hermes_db.core.values import decode_text, encode_text


def replay_files(resource):
    owned = resource.scope.require_store_id()
    with resource.read() as conn:
        jobs = list(conn.scalars(select(file_jobs.c.board_id).where(file_jobs.c.store_id == owned,
            file_jobs.c.owner_home == encode_text(str(resource.scope.profile_home)),
            (file_jobs.c.state != "done") | (file_jobs.c.action == "import"))))
    for board_id in jobs:
        files.run_job(resource, board_id)
    _orphan_imports(resource)
    return len(jobs)


def _orphan_imports(resource):
    from hermes_db.operations.kanban_file_cleanup import _remove_directory
    home = resource.scope.profile_home
    root = home / "kanban" / "imports"
    if not root.is_dir():
        return
    with files.local_files_lock(home):
        # A disconnected writer may still be resolving COMMIT. Fence it before
        # taking a fresh snapshot, while import preparation shares our file gate.
        with resource.write() as conn:
            files.lock_files(conn, resource)
        with resource.read() as conn:
            live = {decode_text(value) for value in conn.scalars(select(file_jobs.c.stage_root).where(
                file_jobs.c.store_id == resource.scope.require_store_id(), file_jobs.c.stage_root.is_not(None)))}
        for stage in root.iterdir():
            if re.fullmatch("[0-9a-f]{32}", stage.name) and str(stage) not in live and owns_import_stage(resource, stage):
                _remove_directory(stage, parent=root)


def owns_import_stage(resource, stage):
    import json
    from hermes_db.integration.transfer.move_values import resource_key
    marker = stage / ".owner.json"
    if not marker.is_file() or marker.is_symlink():
        return False
    return json.loads(marker.read_text(encoding="utf-8-sig")) == dict(store_id=resource.scope.require_store_id(),
        home=str(resource.scope.profile_home), target=resource_key(resource._transactions))


def terminal_workspaces(resource):
    from hermes_db.operations.kanban_workspace_cleanup import cleanup_workspace
    owned = resource.scope.require_store_id()
    with resource.read() as conn:
        rows = list(conn.execute(select(tasks.c.board_id, kanban_boards.c.slug, tasks.c.id).join(kanban_boards,
            (tasks.c.store_id == kanban_boards.c.store_id) & (tasks.c.board_id == kanban_boards.c.board_id)).where(
            tasks.c.store_id == owned, tasks.c.status.in_((b"done", b"archived", b"failed", b"cancelled")),
            tasks.c.workspace_path.is_not(None), tasks.c.workspace_kind.in_((b"scratch", b"worktree")))))
    for board_id, slug, task_id in rows:
        with BoardResource(resource, board_id, slug) as board, board_files(board):
            cleanup_workspace(board, decode_text(task_id))
    return len(rows)


def pending_workspaces(resource):
    import json
    from hermes_db.tables.kanban_workspaces import paths
    from hermes_db.operations.kanban_workspace_cleanup import resume_pending
    with resource.read() as conn:
        pending = list(conn.execute(select(paths.c.path_key, paths.c.cleanup_token, paths.c.cleanup_payload).where(
            paths.c.store_id == resource.scope.require_store_id(), paths.c.cleanup_token.is_not(None))))
    if not pending:
        return
    with files.local_files_lock(resource.scope.profile_home):
        for path_key, token, raw in pending:
            if raw is None:
                from hermes_db.errors import StorageConfigurationError
                raise StorageConfigurationError("Workspace cleanup lacks a captured intent; retain files for explicit reconciliation")
            payload = json.loads(bytes(raw))
            with BoardResource(resource, payload["board_id"], payload["slug"]) as board, board_files(board):
                resume_pending(board, payload["task"], decode_text(path_key), token)
