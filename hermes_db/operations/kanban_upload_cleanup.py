"""Reclaim chunks only after an exact durable command receipt or terminal execution proof."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
from sqlalchemy import select

from hermes_db.errors import StorageBusyError, StorageConfigurationError
from hermes_db.tables.kanban_commands import command_receipts


@contextmanager
def _gate(root):
    from pm.filesystem import lock_path, unlock_fd
    descriptor = lock_path(root / ".lock", timeout=1, create_dir=False)
    if descriptor is None:
        raise StorageBusyError("Worker upload stage is busy")
    try:
        yield
    finally:
        unlock_fd(descriptor)
        os.close(descriptor)


def _completed(resource, manifest, root):
    from hermes_db.integration.transfer.move_values import resource_key
    marker = root / "command.json"
    owner = manifest["owner"]
    if (owner["store_id"] != resource.scope.require_store_id() or manifest.get("board_target") != resource_key(resource._transactions)
            or Path(owner["profile_home"]).resolve() != resource.scope.profile_home):
        return False  # Another dataset's files stay intact across backend/target switches.
    if marker.is_file() and not marker.is_symlink():
        command = json.loads(marker.read_text(encoding="utf-8"))
        with resource.read() as conn:
            found = conn.scalar(select(command_receipts.c.command_id).where(
                command_receipts.c.store_id == owner["store_id"], command_receipts.c.board_id == owner["board_id"],
                command_receipts.c.command_id == command["command_id"], command_receipts.c.request_digest == command["request_digest"]))
        if found is not None:
            return True
    from hermes_db.integration.observations import terminal_execution
    return terminal_execution(manifest["session_store"], manifest["execution_id"], manifest["generation"])


def reclaim(resource):
    base = resource.scope.profile_home / "kanban" / "uploads"
    if not base.is_dir():
        return 0
    removed = 0
    for root in base.glob("*/*"):
        if not re.fullmatch("[0-9a-f]{64}", root.parent.name) or not re.fullmatch("[0-9a-f]{32}", root.name):
            continue
        if root.resolve() != root or not root.is_relative_to(base):
            raise StorageConfigurationError("Upload cleanup directory is redirected")
        with _gate(root):
            path = root / "manifest.json"
            if path.is_symlink():
                raise StorageConfigurationError("Upload cleanup manifest is redirected")
            if not path.is_file():
                continue
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
            if not _completed(resource, manifest, root):
                continue
            from utils import atomic_write_bytes
            atomic_write_bytes(root / ".reclaimed", b"complete", mode=0o600, fsync_dir=True)
            for chunk in root.glob("*.part"):
                if re.fullmatch(r"\d{6}\.part", chunk.name):
                    chunk.unlink()
                    removed += 1
    return removed
