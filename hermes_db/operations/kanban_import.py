"""One scoped transaction creates the imported graph and its durable file-publication job."""

from pathlib import Path
import shutil
import tempfile
import time
from uuid import uuid4
from sqlalchemy import LargeBinary, select

from hermes_db.domains.kanban import BoardResource
from hermes_db.errors import StorageConfigurationError, UnknownCommitError
from hermes_db.operations import kanban_boards as boards, kanban_file_jobs as files
from hermes_db.operations.kanban_archive_format import read_archive
from hermes_db.operations.kanban_transfer import TABLES, scrub_runtime
from hermes_db.repositories import kanban as repo
from hermes_db.repositories.kanban_workspaces import canonical_path
from hermes_db.tables.kanban_file_jobs import file_jobs
from hermes_db.core.values import encode_text


def compensate_stage(stage, root, primary):
    from hermes_db.operations.kanban_file_cleanup import _remove_directory
    try:
        _remove_directory(stage, parent=root)
    except (OSError, StorageConfigurationError) as error:
        primary.add_note(f"Private import stage cleanup failed ({type(error).__name__}); retain the original stage for reconciliation")


def insert_import_row(conn, store, table, row, *, returning=False):
    values = {name: encode_text(value) if isinstance(table.c[name].type, LargeBinary) else value for name, value in row.items()}
    statement = table.insert().values(**repo.owner(store), **values)
    return conn.scalar(statement.returning(table.c.id)) if returning else conn.execute(statement)


def _insert_rows(conn, store, tables, parked):
    for row in tables["tasks"]:
        insert_import_row(conn, store, TABLES["tasks"], row)
    run_ids = {}
    for original in sorted(tables["task_runs"], key=lambda row: row["id"]):
        row = dict(original)
        old = row.pop("id")
        run_ids[old] = insert_import_row(conn, store, TABLES["task_runs"], row, returning=True)
    for name in ("task_links", "task_comments", "task_attachments", "task_events"):
        for original in sorted(tables[name], key=lambda row: row.get("id", 0)):
            row = {name: value for name, value in original.items() if name != "id"}
            if name == "task_events" and row["run_id"] is not None:
                if row["run_id"] not in run_ids:
                    raise ValueError("Board archive event references an unknown run")
                row["run_id"] = run_ids[row["run_id"]]
            insert_import_row(conn, store, TABLES[name], row)
    for row in tables["tasks"]:
        repo.event(conn, store, row["id"], "imported", {"board": store.slug, "parked": row["id"] in parked})


def _target_slug(conn, resource, requested):
    stem = requested[:58].rstrip("-_") or "board"
    candidate, suffix = requested, 2
    while True:
        pending = conn.scalar(select(file_jobs.c.board_id).where(file_jobs.c.store_id == resource.scope.require_store_id(),
            file_jobs.c.slug == candidate, file_jobs.c.state == "pending").limit(1))
        if candidate != "default" and boards._lookup(conn, resource, candidate) is None and pending is None:
            return candidate
        candidate, suffix = f"{stem}-{suffix}", suffix + 1


def _prepare_rows(tables, fields):
    from hermes_cli.kanban_transfer_values import reanchor_tables
    scrub_runtime(tables)
    parked = set()
    for task in tables["tasks"]:
        if task["workspace_kind"] in {"dir", "worktree"} and task["status"] in {"ready", "running", "todo", "scheduled"}:
            task["status"] = "triage"
            parked.add(task["id"])
    mapping = {}
    for row in tables["task_attachments"]:
        original = row["stored_path"]
        member = row["stored_path"].removeprefix("attachments/")
        row["stored_path"] = str(Path(fields["attachments_root"]).joinpath(*member.split("/")))
        row["path_key"] = canonical_path(row["stored_path"])
        mapping[original] = row["stored_path"]
    reanchor_tables(tables, mapping)
    return parked


def _stage(extracted, resource, board_id):
    from hermes_cli.archive_safe import copy_regular_files
    from hermes_db.integration.transfer.move_values import resource_key
    from utils import atomic_json_write
    home = resource.scope.profile_home
    root = home / "kanban" / "imports"
    if root.resolve() != home.resolve() / "kanban" / "imports":
        raise StorageConfigurationError("Board import staging root is redirected")
    root.mkdir(parents=True, exist_ok=True)
    stage = root / board_id
    stage.mkdir(mode=0o700)
    try:
        atomic_json_write(stage / ".owner.json", {"store_id": resource.scope.require_store_id(),
            "home": str(home), "target": resource_key(resource._transactions)}, mode=0o600)
        for name in ("manifest.json", "board.json", "data.json"):
            shutil.copyfile(extracted / name, stage / name)
        for name in ("attachments", "logs"):
            copy_regular_files(extracted / name, stage / name)
        return stage
    except BaseException as primary:
        compensate_stage(stage, root, primary)
        raise


def _commit_graph(resource, requested, board_id, stage, tables, fields, parked):
    with resource.write() as conn:
        files.lock_files(conn, resource)
        boards._registry_lock(conn, resource)
        target = _target_slug(conn, resource, requested)
        boards._save(conn, resource, target, None, True, new_board_id=board_id)
        board = BoardResource(resource, board_id, target)
        try:
            conn.execute(file_jobs.insert().values(store_id=resource.scope.require_store_id(), board_id=board_id,
                slug=target, action="import", state="pending", created_at=int(time.time()), stage_root=encode_text(str(stage)),
                **{name: encode_text(value) for name, value in fields.items()}))
            _insert_rows(conn, board, tables, parked)
        finally:
            board.close()
    return target


def _import(extracted, requested, *, activate):
    from hermes_cli import kanban_db as kb
    from hermes_db.factory import acquire_profile_domain
    manifest, tables, metadata = read_archive(extracted)
    requested = kb._normalize_board_slug(requested or manifest.get("board") or extracted.name)
    if not requested:
        raise ValueError("Pass an explicit Board slug for this archive")
    with acquire_profile_domain("kanban_tasks") as resource:
        board_id = uuid4().hex
        fields = files.prepare(resource, {"board_id": board_id, "slug": requested})
        parked = _prepare_rows(tables, fields)
        with files.local_files_lock(resource.scope.profile_home):
            stage = _stage(extracted, resource, board_id)
            try:
                target = _commit_graph(resource, requested, board_id, stage, tables, fields, parked)
            except UnknownCommitError as error:
                error.add_note(f"Board import {board_id} may be committed; retain its original stage and inspect the file job")
                raise
            except BaseException as primary:
                compensate_stage(stage, resource.scope.profile_home / "kanban" / "imports", primary)
                raise
        result = files.run_job(resource, board_id)
    if activate:
        kb.set_current_board(target)
    warnings = [f"{len(parked)} task(s) moved to triage — configure their directory or worktree on this machine"] if parked else []
    if result.get("stage_cleanup_pending"):
        warnings.append("The Board is active; private import-stage cleanup is pending")
    counts = {name: len(rows) for name, rows in tables.items()}
    counts["task_events"] += len(tables["tasks"])
    return dict(board=target, requested_board=requested, renamed=target != requested, name=metadata.get("name") or target,
        path=str(kb.board_dir(target)), db_path=None, backend="postgresql", board_id=board_id,
        source={name: manifest.get(name) for name in ("board", "exported_at", "hermes_version")}, counts=counts,
        attachments_restored=len(tables["task_attachments"]), tasks_parked=len(parked), warnings=warnings, activated=bool(activate))


def import_board(archive_path, slug=None, *, activate=False):
    from hermes_cli.archive_safe import archive_root_dirs, safe_extract_targz
    archive = Path(archive_path).expanduser()
    roots = archive_root_dirs(archive)
    if len(roots) != 1:
        raise ValueError("A Board archive must contain exactly one top-level directory")
    root = roots.pop()
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        safe_extract_targz(archive, staging)
        return _import(staging / root, slug, activate=activate)
