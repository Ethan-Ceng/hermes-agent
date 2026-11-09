"""Private content work uses a PM file gate with no borrowed database connection."""
from hermes_db.domains.rooms.attachments import rules as _storage_shared_1

import os
import secrets
from contextlib import contextmanager
from hermes_db.errors import StorageBusyError
from hermes_db.domains.rooms.attachments import rules as native
from hermes_db.domains.rooms.attachments.rules import (AttachmentIntegrityError, MAX_ATTACHMENT_BYTES, _BLOB_ID_RE)
from hermes_dir_acl import make_user_dir
from pathlib import Path
from typing import Any, Sequence
import hashlib
import stat


@contextmanager
def files_gate(root):
    from pm.filesystem import lock_path, unlock_fd
    descriptor = lock_path(root / ".attachment-files.lock", timeout=10, create_dir=False)
    if descriptor is None:
        raise StorageBusyError("Room attachment files are being changed; retry after the operation completes")
    try:
        yield
    finally:
        unlock_fd(descriptor)
        os.close(descriptor)


def replay_cleanup(store):
    from hermes_db.domains.rooms.attachments.postgres import metadata as cleanup
    with store._store() as resource:
        jobs = cleanup.pending_jobs(resource, store.namespace)
    for blob_id in jobs:
        store._blob_path(blob_id).unlink(missing_ok=True)
        with store._store() as resource:
            cleanup.complete_job(resource, store.namespace, blob_id)


def sweep_locked(store):
    from hermes_db.domains.rooms.attachments.postgres import metadata as cleanup
    with store._store() as resource:
        live = cleanup.live_blobs(resource)
    for path in tuple(store.blob_root.iterdir()):
        orphan = _storage_shared_1._BLOB_ID_RE.fullmatch(path.name) is not None and path.name not in live
        if not (orphan or path.name.startswith((".tmp-", ".prune-"))):
            continue
        quarantine = store.blob_root / (".prune-" + secrets.token_hex(16))
        try:
            os.replace(path, quarantine)
        except FileNotFoundError:
            continue
        quarantine.unlink(missing_ok=True)


class AttachmentContent:
    """Private canonical bytes and the shared commitment convenience call; no database connection."""

    def _prepare_private_root(self) -> None:
        make_user_dir(self.root, parents=True, exist_ok=True, mode=0o700)
        make_user_dir(self.blob_root, parents=True, exist_ok=True, mode=0o700)
        for path in (self.root, self.blob_root):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass

    def _blob_path(self, blob_id: str) -> Path:
        if _BLOB_ID_RE.fullmatch(blob_id) is None:
            raise AttachmentIntegrityError("stored blob id is invalid")
        return self.blob_root / blob_id

    def _write_blob(self, target: Path, data: bytes) -> None:
        from utils import atomic_write_bytes
        # ``.tmp-`` staging names are what the orphan sweep reclaims after a crash.
        atomic_write_bytes(target, data, tmp_prefix=".tmp-", mode=0o600, fsync_dir=True)

    def _open_blob(self, *, blob_id: str, size: int) -> int:
        """Open the regular blob file and fence its size against the durable row."""
        path = self._blob_path(blob_id)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise AttachmentIntegrityError("canonical attachment blob is unavailable") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                raise AttachmentIntegrityError("canonical attachment blob size changed")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _read_blob(self, *, blob_id: str, size: int, sha256: str) -> bytes:
        descriptor = self._open_blob(blob_id=blob_id, size=size)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                data = handle.read(MAX_ATTACHMENT_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
            raise AttachmentIntegrityError("canonical attachment blob failed SHA-256 validation")
        return data

    def _read_blob_range(self, *, blob_id: str, size: int, offset: int, length: int) -> bytes:
        """One slice of the blob; the row's SHA-256 is the caller's whole-file digest and the
        receiver verifies the reassembled bytes against it, so no slice is hashed here."""
        descriptor = self._open_blob(blob_id=blob_id, size=size)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                handle.seek(offset)
                data = handle.read(length)
        finally:
            os.close(descriptor)
        if len(data) != min(length, size - offset):
            raise AttachmentIntegrityError("canonical attachment blob size changed")
        return data

    @staticmethod
    def _metadata(row: object, *, idempotent: bool = False) -> dict[str, Any]:
        result = {
            "attachment_id": str(row["attachment_id"]),
            "kind": str(row["kind"]),
            "name": str(row["name"]),
            "size": int(row["size"]),
            "mime": str(row["mime"]),
            "sha256": str(row["sha256"]),
            "state": str(row["state"]),
            "created_at": float(row["created_at"]),
            "idempotent": idempotent,
        }
        if row["event_id"] is not None:
            result["event_id"] = str(row["event_id"])
        return result

    def commit_message(
        self,
        *,
        room_id: Any,
        event_id: Any,
        manifest: Any,
        recipient_member_ids: Sequence[str],
        viewer_access: bool = False,
        retention_seconds: float | None = None,
        hold_until_event: bool = False,
    ) -> list[dict[str, Any]]:
        normalized, _transitioned = self.commit_message_with_receipt(
            room_id=room_id,
            event_id=event_id,
            manifest=manifest,
            recipient_member_ids=recipient_member_ids,
            viewer_access=viewer_access,
            retention_seconds=retention_seconds,
            hold_until_event=hold_until_event,
        )
        return normalized
