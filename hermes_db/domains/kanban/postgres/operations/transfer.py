"""Portable PG Board snapshots; local file preparation never retains a connection."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from sqlalchemy import select

from hermes_db.domains.kanban.routing.files import BoardFiles, _path
from hermes_db.domains.kanban.postgres.queries import kanban as repo
from hermes_db.tables.kanban import tasks, links, comments, events, runs
from hermes_db.tables.kanban_artifacts import attachments

FORMAT_VERSION = 2
TABLES = {"tasks": tasks, "task_links": links, "task_comments": comments,
          "task_events": events, "task_runs": runs, "task_attachments": attachments}
LOCAL_TASK_FIELDS = ("claim_lock", "claim_expires", "worker_pid", "worker_started_at", "current_run_id",
                     "last_heartbeat_at", "session_id", "project_id", "last_failure_error", "workspace_path", "branch_name")


def snapshot(store):
    result = {}
    with store.read() as conn:
        for name, table in TABLES.items():
            columns = [column for column in table.columns if column.name not in {"store_id", "board_id", "path_key"}]
            result[name] = [repo.decode_record(row) for row in conn.execute(select(*columns).where(repo.scope(table, store))).mappings()]
    return result


def scrub_runtime(tables):
    for task in tables["tasks"]:
        for field in LOCAL_TASK_FIELDS:
            task[field] = None
        task["consecutive_failures"] = 0
        if task["status"] == "running":
            task["status"] = "ready"
    for run in tables["task_runs"]:
        for field in ("claim_lock", "claim_expires", "worker_pid", "worker_started_at", "last_heartbeat_at"):
            run[field] = None
        if run["status"] == "running":
            run.update(status="released", outcome=run["outcome"] or "reclaimed", ended_at=run["ended_at"] or int(time.time()))


def copy_registered_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    digest = hashlib.sha256()
    with target.open("rb") as copied:
        for chunk in iter(lambda: copied.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"size": target.stat().st_size, "sha256": digest.hexdigest()}


def _attachments(tables, root, staged, include):
    from hermes_cli.kanban_transfer_values import reanchor_tables
    proofs = {}
    if not include:
        omitted = len(tables["task_attachments"])
        tables["task_attachments"] = []
        return proofs, [f"{omitted} attachment record(s) omitted by request"] if omitted else []
    root = root.resolve()
    mapping = {}
    for row in tables["task_attachments"]:
        source = Path(row["stored_path"]).resolve(strict=True)
        if not source.is_relative_to(root) or source == root:
            raise ValueError("Attachment is outside the managed Board root; retain it or explicitly export without attachments")
        member = "attachments/" + source.relative_to(root).as_posix()
        if member not in proofs:
            proofs[member] = copy_registered_file(source, staged / member)
        mapping[row["stored_path"]] = member
        row["stored_path"] = member
    reanchor_tables(tables, mapping)
    return proofs, []


def export_board(board, output_path, *, include_attachments=True, include_logs=False):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_cli.archive_safe import copy_regular_files, make_targz
    from hermes_cli.kanban_transfer import ARCHIVE_FORMAT, _write_json
    from hermes_cli.version_info import get_version_info
    slug = kb._normalize_board_slug(board) or kb.get_current_board()
    base = str(Path(output_path).expanduser()).removesuffix(".tar.gz").removesuffix(".tgz")
    Path(base).parent.mkdir(parents=True, exist_ok=True)
    with kbc.connect_closing(board=slug) as store:
        tables = snapshot(store)
        frame = BoardFiles(store.scope.profile_home, store.board_id, store.slug)
    scrub_runtime(tables)
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary) / slug
        staged.mkdir()
        proofs, warnings = _attachments(tables, _path(frame, "HERMES_KANBAN_ATTACHMENTS_ROOT", "attachments"), staged, include_attachments)
        metadata = kb.read_board_metadata(slug)
        metadata.pop("db_path", None)
        metadata.update(default_workdir=None, project_id=None)
        _write_json(staged / "board.json", metadata)
        _write_json(staged / "data.json", {"format_version": FORMAT_VERSION, "tables": tables})
        logs = copy_regular_files(_path(frame, None, "logs"), staged / "logs") if include_logs else 0
        manifest = dict(format=ARCHIVE_FORMAT, format_version=FORMAT_VERSION, backend="postgresql", board=slug,
            board_name=metadata.get("name") or slug, exported_at=int(time.time()), hermes_version=get_version_info().base_version,
            includes={"attachments": bool(include_attachments), "logs": bool(include_logs)}, files=proofs,
            counts={**{name: len(rows) for name, rows in tables.items()}, "attachment_files": len(proofs), "log_files": logs})
        _write_json(staged / "manifest.json", manifest)
        archive = make_targz(base, temporary, slug)
    return dict(board=slug, archive=archive, size=Path(archive).stat().st_size, counts=manifest["counts"], warnings=warnings)
