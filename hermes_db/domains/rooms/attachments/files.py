"""Private content work uses a PM file gate with no borrowed database connection."""

import os
import secrets
from contextlib import contextmanager
from hermes_db.errors import StorageBusyError
from hermes_db.domains.rooms.attachments.postgres import metadata as cleanup
from gateway import hosted_room_attachments as native


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
    with store._store() as resource:
        jobs = cleanup.pending_jobs(resource, store.namespace)
    for blob_id in jobs:
        store._blob_path(blob_id).unlink(missing_ok=True)
        with store._store() as resource:
            cleanup.complete_job(resource, store.namespace, blob_id)


def sweep_locked(store):
    with store._store() as resource:
        live = cleanup.live_blobs(resource)
    for path in tuple(store.blob_root.iterdir()):
        orphan = native._BLOB_ID_RE.fullmatch(path.name) is not None and path.name not in live
        if not (orphan or path.name.startswith((".tmp-", ".prune-"))):
            continue
        quarantine = store.blob_root / (".prune-" + secrets.token_hex(16))
        try:
            os.replace(path, quarantine)
        except FileNotFoundError:
            continue
        quarantine.unlink(missing_ok=True)
