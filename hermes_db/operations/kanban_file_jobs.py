"""Retirement commits before local file work, which remains replayable after interruption."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
import time
from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert

from hermes_db.domains.kanban_files import BoardFiles, _path, content_root
from hermes_db.errors import StorageBusyError, StorageConfigurationError
from hermes_db.tables.kanban_file_jobs import file_jobs as jobs, file_locks as locks
from hermes_db.core.values import decode_text, encode_text

ROOT_FIELDS = ("data_root", "attachments_root", "workspaces_root", "logs_root")


@contextmanager
def local_files_lock(home):
    from pm.filesystem import lock_path, unlock_fd
    descriptor = lock_path(Path(home) / "kanban" / ".board-files.lock", timeout=10, create_dir=True)
    if descriptor is None:
        raise StorageBusyError("Local Board files are being changed; retry after the operation completes")
    try:
        yield
    finally:
        unlock_fd(descriptor)
        os.close(descriptor)


def under_root(key, root):
    import unicodedata
    root_key = os.path.normcase(unicodedata.normalize("NFC", os.path.normpath(root)))
    return key == root_key or key.startswith(root_key + os.sep)


def guard_reference(conn, store, key):
    if key is None:
        return
    retired = conn.execute(select(*(jobs.c[name] for name in ROOT_FIELDS)).where(
        jobs.c.store_id == store.scope.require_store_id(),
        (jobs.c.action == "delete") | ((jobs.c.action == "import") & (jobs.c.state != "done")))).all()
    if any(under_root(key, decode_text(root)) for row in retired for root in row):
        raise StorageBusyError("Board content has been retired; use an active Board content root")


def lock_files(conn, store):
    conn.execute(insert(locks).values(store_id=store.scope.require_store_id()).on_conflict_do_nothing())
    conn.execute(select(locks.c.store_id).where(locks.c.store_id == store.scope.require_store_id()).with_for_update()).one()


def job_key(store, board_id):
    return and_(jobs.c.store_id == store.scope.require_store_id(), jobs.c.board_id == board_id)


def require_settled_slug(conn, store, slug):
    pending = conn.scalar(select(jobs.c.board_id).where(jobs.c.store_id == store.scope.require_store_id(),
        jobs.c.slug == slug, jobs.c.owner_home == encode_text(str(store.scope.profile_home)), jobs.c.state == "pending").limit(1))
    if pending is not None:
        raise StorageBusyError("Board file operation is pending; retry its retirement or reconcile before reusing the slug")


def prepare(store, row):
    frame = BoardFiles(store.scope.profile_home, row["board_id"], row["slug"])
    data = content_root(frame)
    if data.resolve() != frame.home.resolve() / "kanban" / "data" / frame.board_id:
        raise StorageConfigurationError("Board data generation is redirected; preserve it for manual reconciliation")
    fields = dict(owner_home=str(frame.home), data_root=str(data.resolve()))
    for name, env_var, leaf in (("attachments_root", "HERMES_KANBAN_ATTACHMENTS_ROOT", "attachments"),
                                ("workspaces_root", "HERMES_KANBAN_WORKSPACES_ROOT", "workspaces"), ("logs_root", None, "logs")):
        root = _path(frame, env_var, leaf)
        override = os.environ.get(env_var, "").strip() if env_var else ""
        expected = Path(override).expanduser().resolve() / frame.board_id if override else frame.home.resolve() / "kanban" / "data" / frame.board_id / leaf
        if root.resolve() != expected:
            raise StorageConfigurationError("Board content root contains a redirected generation path; preserve it for manual reconciliation")
        fields[name] = str(expected)
    return fields


def record(conn, store, row, fields, *, archive):
    action = "archive" if archive else "delete"
    existing = conn.execute(select(jobs).where(job_key(store, row["board_id"]))).mappings().one_or_none()
    if existing is not None:
        if existing["action"] == action:
            return
        allowed = {("import", "archive"), ("import", "delete"), ("archive", "delete")}
        if (existing["state"] != "done" or (existing["action"], action) not in allowed
                or existing["stage_root"] is not None):
            raise StorageBusyError("Complete the existing Board file operation before changing its action")
        conn.execute(update(jobs).where(job_key(store, row["board_id"])).values(
            action=action, state="pending", created_at=int(time.time()),
            **{key: encode_text(value) for key, value in fields.items()}))
        return
    conn.execute(jobs.insert().values(store_id=store.scope.require_store_id(), board_id=row["board_id"],
        slug=row["slug"], action=action, created_at=int(time.time()), **{key: encode_text(value) for key, value in fields.items()}))


def _archive_files(row):
    from utils import atomic_json_write
    from hermes_cli.kanban_db_boards import _read_metadata_file
    home = Path(row["owner_home"])
    boards_root = home / "kanban" / "boards"
    source = boards_root / row["slug"]
    target = boards_root / "_archived" / f"{row['slug']}-{row['board_id']}"
    resolved_root = boards_root.resolve()
    if any(not path.resolve().is_relative_to(resolved_root) or path.resolve() == resolved_root for path in (source, target)):
        raise StorageConfigurationError("Board archive paths escape the owning boards directory")
    # The UUID target belongs to this persisted intent; a retry never moves a new generation.
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            source.rename(target)
        else:
            target.mkdir()
    metadata_path = target / "board.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path.exists() else _read_metadata_file(row["slug"])
    metadata.pop("db_path", None)
    metadata.update(slug=row["slug"], archived=True)
    source.mkdir(parents=True, exist_ok=True)
    atomic_json_write(metadata_path, metadata, indent=2)
    atomic_json_write(target / "contents.json", {"backend": "postgresql", "board_id": row["board_id"],
        "roots": {name: row[name] for name in ROOT_FIELDS}}, indent=2)
    atomic_json_write(source / "board.json", metadata, indent=2)
    return str(target)


def _read_job(store, board_id):
    from hermes_db.repositories.kanban import decode_record
    with store.read() as conn:
        raw = conn.execute(select(jobs).where(job_key(store, board_id))).mappings().one()
        row = decode_record(raw)
    if Path(row["owner_home"]).resolve() != store.scope.profile_home:
        raise StorageConfigurationError("Board file operation belongs to another local Profile home")
    return row


def set_job_state(store, board_id, state):
    with store.write() as conn:
        lock_files(conn, store)
        conn.execute(update(jobs).where(job_key(store, board_id)).values(state=state))


def pending_delete(store, slug):
    with store.read() as conn:
        return conn.scalar(select(jobs.c.board_id).where(jobs.c.store_id == store.scope.require_store_id(), jobs.c.slug == slug,
            jobs.c.action == "delete", jobs.c.state != "done", jobs.c.owner_home == encode_text(str(store.scope.profile_home))))


def settle_import_stage(store, board_id):
    with store.read() as conn:
        row = conn.execute(select(jobs.c.action, jobs.c.state, jobs.c.stage_root).where(job_key(store, board_id))).first()
    if row is not None and row.action == "import" and row.state == "done" and row.stage_root is not None:
        run_job(store, board_id)


def run_job(store, board_id):
    # Re-read after the OS lock: another process may have completed this exact intent.
    with local_files_lock(store.scope.profile_home):
        row = _read_job(store, board_id)
        if row["action"] == "import":
            from hermes_db.operations.kanban_import_files import finish_import
            return finish_import(store, row)
        if row["action"] == "delete":
            from hermes_db.operations.kanban_file_cleanup import delete_files
            return delete_files(store, row)
        target = str(Path(row["owner_home"]) / "kanban" / "boards" / "_archived" / f"{row['slug']}-{board_id}")
        if row["state"] != "done":
            target = _archive_files(row)
            set_job_state(store, board_id, "done")
        return {"new_path": target, "files_pending": False}
