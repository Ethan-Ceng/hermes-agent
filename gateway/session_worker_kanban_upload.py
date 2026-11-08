"""Authenticated, bounded file preparation; Board effects keep their ordinary receipt txn."""

import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re

from hermes_state_runtime import RuntimeStoreError

CHUNK_BYTES = 256 * 1024


def _proof(upload_id, size, digest):
    from hermes_cli.kanban_db import KANBAN_ATTACHMENT_MAX_BYTES, AttachmentTooLarge
    if type(size) is not int or size < 0:
        raise RuntimeStoreError("invalid_params")
    if size > KANBAN_ATTACHMENT_MAX_BYTES:
        raise AttachmentTooLarge("attachment exceeds 25 MB limit")
    if (not isinstance(upload_id, str) or re.fullmatch("[0-9a-f]{32}", upload_id) is None
            or not isinstance(digest, str) or re.fullmatch("[0-9a-f]{64}", digest) is None):
        raise RuntimeStoreError("invalid_params")


def _manifest(context, params, principal, upload_id, size, digest):
    _proof(upload_id, size, digest)
    return {"owner": context["owner"], "board_target": context["board_target"], "session_store": context["session_store"],
            "execution_id": params["execution_id"], "generation": params["generation"],
            "principal": principal, "upload_id": upload_id, "size": size, "sha256": digest}


@contextmanager
def _stage(manifest):
    from hermes_dir_acl import make_user_dir
    from pm.filesystem import lock_path, unlock_fd
    from hermes_db.errors import StorageBusyError, StorageConfigurationError
    owner = manifest["owner"]
    home = Path(owner["profile_home"]).resolve()
    namespace = hashlib.sha256(json.dumps([owner["store_id"], owner["board_id"], manifest["execution_id"],
        manifest["generation"], manifest["principal"]], ensure_ascii=True).encode()).hexdigest()
    root = home / "kanban" / "uploads" / namespace / manifest["upload_id"]
    make_user_dir(root, mode=0o700, parents=True, exist_ok=True)
    if root.resolve() != root or any(path.is_symlink() for path in (root, root.parent, root.parent.parent, home / "kanban")):
        raise StorageConfigurationError("Worker upload stage must remain inside its owning Profile")
    fd = lock_path(root / ".lock", timeout=10, create_dir=False)
    if fd is None:
        raise StorageBusyError("Worker upload stage is busy")
    try:
        if (root / ".reclaimed").exists():
            raise RuntimeStoreError("upload_completed")
        path = root / "manifest.json"
        if path.is_symlink():
            raise StorageConfigurationError("Worker upload manifest is redirected")
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8-sig")) != manifest:
                raise RuntimeStoreError("admission_conflict")
        else:
            from utils import atomic_json_write
            atomic_json_write(path, manifest, mode=0o600)
        yield root
    finally:
        unlock_fd(fd)
        os.close(fd)


def write_chunk(context, params, principal):
    payload = params["payload"]
    if set(payload) != {"target", "upload_id", "size", "sha256", "index", "data"}:
        raise RuntimeStoreError("invalid_params")
    manifest = _manifest(context, params, principal, payload["upload_id"], payload["size"], payload["sha256"])
    index, encoded = payload["index"], payload["data"]
    count = max(1, (manifest["size"] + CHUNK_BYTES - 1) // CHUNK_BYTES)
    if (type(index) is not int or not 0 <= index < count or not isinstance(encoded, str)
            or len(encoded) > 4 * ((CHUNK_BYTES + 2) // 3)):
        raise RuntimeStoreError("invalid_params")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise RuntimeStoreError("invalid_params") from error
    expected = min(CHUNK_BYTES, manifest["size"] - index * CHUNK_BYTES)
    if len(data) != expected:
        raise RuntimeStoreError("invalid_params")
    with _stage(manifest) as root:
        path = root / f"{index:06d}.part"
        if path.is_symlink():
            raise RuntimeStoreError("permission_denied")
        if path.exists():
            if path.read_bytes() != data:
                raise RuntimeStoreError("admission_conflict")
        else:
            from utils import atomic_write_bytes
            atomic_write_bytes(path, data, mode=0o600, fsync_dir=True)
    return {"index": index, "size": len(data)}


def commit_upload(store, context, params, principal, args, kwargs):
    from hermes_cli import kanban_db as kb
    if len(args) != 5 or set(kwargs) - {"content_type", "uploaded_by", "board", "max_bytes"}:
        raise RuntimeStoreError("invalid_params")
    task_id, filename, upload_id, size, digest = args
    manifest = _manifest(context, params, principal, upload_id, size, digest)
    with _stage(manifest) as root:
        from utils import atomic_json_write
        marker = root / "command.json"
        command = {"command_id": store.command.command_id, "request_digest": store.command.request_digest}
        if marker.is_symlink():
            raise RuntimeStoreError("permission_denied")
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8-sig")) != command:
            raise RuntimeStoreError("admission_conflict")
        atomic_json_write(marker, command, mode=0o600)
        count = max(1, (size + CHUNK_BYTES - 1) // CHUNK_BYTES)
        chunks = []
        for index in range(count):
            path = root / f"{index:06d}.part"
            if path.is_symlink() or not path.is_file():
                raise RuntimeStoreError("upload_incomplete")
            chunk = path.read_bytes()
            if len(chunk) != min(CHUNK_BYTES, size - index * CHUNK_BYTES):
                raise RuntimeStoreError("upload_incomplete")
            chunks.append(chunk)
        data = b"".join(chunks)
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeStoreError("admission_conflict")
    return kb.store_attachment_bytes(store, task_id, filename, data, **kwargs)
