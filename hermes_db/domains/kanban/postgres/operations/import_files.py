"""Publish a committed import's private files before atomically making its Board active."""

import logging
from pathlib import Path
from sqlalchemy import select, update

from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.kanban.postgres.operations.archive_format import fingerprint, read_archive
from hermes_db.domains.kanban.postgres.operations.transfer import copy_registered_file
from hermes_db.domains.kanban.postgres.operations.file_jobs import job_key, lock_files
from hermes_db.tables.kanban import kanban_boards
from hermes_db.tables.kanban_file_jobs import file_jobs

logger = logging.getLogger(__name__)


def _publish(source, target, board_id, proofs):
    if not source.is_dir():
        return
    target = Path(target)
    if not target.is_absolute() or target.resolve() != target or board_id not in target.parts:
        raise StorageConfigurationError("Imported content root is redirected or outside its generation")
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Private Board import stage contains a symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if destination.resolve() != destination:
            raise StorageConfigurationError("Imported content destination is redirected")
        expected = proofs.get(source.name + "/" + relative.as_posix()) or fingerprint(path)
        if destination.exists():
            actual = fingerprint(destination)
        else:
            actual = copy_registered_file(path, destination)
        if actual != expected:
            raise ValueError("Imported content fingerprint mismatch; preserve the stage and target for reconciliation")


def _configuration(row, metadata):
    from utils import atomic_json_write
    home = Path(row["owner_home"])
    directory = home / "kanban" / "boards" / row["slug"]
    if directory.resolve() != directory:
        raise StorageConfigurationError("Imported Board configuration directory is redirected")
    marker = directory / ".import-id"
    if directory.exists():
        if marker.exists():
            if marker.read_text(encoding="utf-8") != row["board_id"]:
                raise StorageConfigurationError("Imported Board configuration belongs to another generation")
        elif any(directory.iterdir()):
            raise StorageConfigurationError("Imported Board configuration directory already contains unrelated files")
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(row["board_id"], encoding="utf-8")
    import time
    clean = {name: str(metadata.get(name) or "") for name in ("name", "description", "icon", "color")}
    clean.update(slug=row["slug"], archived=False, project_id=None, default_workdir=None, created_at=int(time.time()))
    clean["name"] = clean["name"] or row["slug"]
    atomic_json_write(directory / "board.json", clean, indent=2)
    return directory


def _cleanup_stage(row):
    from hermes_db.domains.kanban.postgres.operations.file_cleanup import _remove_directory
    if not row["stage_root"]:
        return False
    try:
        _remove_directory(Path(row["stage_root"]), parent=Path(row["owner_home"]) / "kanban" / "imports")
        return False
    except (OSError, StorageConfigurationError) as error:
        logger.warning("Imported Board %s is active; private stage cleanup is pending: %s", row["slug"], error)
        return True


def _activate(store, row):
    from hermes_db.domains.kanban.postgres.operations.boards import _registry_lock
    with store.write() as conn:
        lock_files(conn, store)
        _registry_lock(conn, store)
        condition = (kanban_boards.c.store_id == store.scope.require_store_id()) & (kanban_boards.c.board_id == row["board_id"])
        current = conn.execute(select(kanban_boards).where(condition).with_for_update()).mappings().one_or_none()
        if current is None:
            raise StorageConfigurationError("Imported Board generation no longer exists")
        conn.execute(update(kanban_boards).where(condition).values(archived=0))
        conn.execute(update(file_jobs).where(job_key(store, row["board_id"])).values(state="done"))


def finish_import(store, row):
    directory = Path(row["owner_home"]) / "kanban" / "boards" / row["slug"]
    if row["state"] != "done":
        stage = Path(row["stage_root"])
        expected_parent = Path(row["owner_home"]) / "kanban" / "imports"
        if not stage.is_relative_to(expected_parent) or stage.resolve() != stage or stage == expected_parent:
            raise StorageConfigurationError("Private Board import stage escaped its owning directory")
        from hermes_db.domains.kanban.postgres.operations.maintenance import owns_import_stage
        if not owns_import_stage(store, stage):
            raise StorageConfigurationError("Private import stage belongs to another database dataset")
        manifest, _tables, metadata = read_archive(stage, private_stage=True)
        for name in ("attachments", "logs"):
            _publish(stage / name, row[name + "_root"], row["board_id"], manifest["files"])
        directory = _configuration(row, metadata)
        _activate(store, row)
    pending = _cleanup_stage(row)
    if not pending and row["stage_root"] is not None:
        with store.write() as conn:
            lock_files(conn, store)
            conn.execute(update(file_jobs).where(job_key(store, row["board_id"]),
                file_jobs.c.action == "import", file_jobs.c.state == "done").values(stage_root=None))
    return {"new_path": str(directory), "files_pending": False, "stage_cleanup_pending": pending}
