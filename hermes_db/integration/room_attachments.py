"""PG attachment composition with connection-free file preparation and cleanup."""
from hermes_db.domains.rooms.attachments import rules as _storage_shared_1

import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time
from contextlib import contextmanager

from hermes_db.domains.rooms.attachments import rules as native
from hermes_db.domains.rooms.api import RoomStoreRef, capture_room_store, normalize_location, open_room_store
from hermes_db.domains.rooms.attachments.api import AttachmentResource
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.rooms.attachments.postgres import metadata as uploads, metadata as commits, metadata as cleanup
from hermes_db.domains.rooms.attachments.postgres import metadata as repo
from hermes_db.domains.rooms.attachments.files import AttachmentContent, files_gate, replay_cleanup, sweep_locked
from hermes_db.domains.rooms.attachments.postgres.reads import AttachmentReaders

_READY = set()
_STARTUP_LOCK = threading.Lock()


class PostgresAttachmentStore(AttachmentReaders, AttachmentContent):
    def __init__(self, db_path, *, root=None, clock=time.time, room_quota_bytes=native.MAX_ROOM_ATTACHMENT_BYTES,
                 gateway_quota_bytes=native.MAX_GATEWAY_BLOB_BYTES, room_quota_count=native.MAX_ROOM_ATTACHMENT_COUNT,
                 gateway_quota_count=native.MAX_GATEWAY_ATTACHMENT_COUNT):
        location = normalize_location(db_path)
        self.db_path = location if isinstance(location, RoomStoreRef) else capture_room_store()
        self.clock = clock
        now = float(clock())
        with open_room_store(self.db_path) as store:
            self.namespace = repo.namespace(store, now)
        if re.fullmatch(r"[0-9a-f]{32}", self.namespace) is None:
            raise StorageConfigurationError("Stored attachment content namespace is invalid")
        base = Path(root) if root is not None else self.db_path.profile_home / "hosted-room-attachments"
        self.root, self.blob_root = base / self.namespace, base / self.namespace / "blobs"
        for name, value in dict(room_quota_bytes=room_quota_bytes, gateway_quota_bytes=gateway_quota_bytes,
                                room_quota_count=room_quota_count, gateway_quota_count=gateway_quota_count).items():
            setattr(self, name, max(1, int(value)))
        self._prepare_private_root()
        key = self.db_path, self.namespace, str(self.root.resolve())
        with _STARTUP_LOCK:
            if key not in _READY:
                self.reconcile_room_events()
                self.prune()
                _READY.add(key)

    @contextmanager
    def _store(self):
        with open_room_store(self.db_path) as resource:
            yield AttachmentResource(resource, self.namespace)

    def put(self, *, room_id, upload_id, kind, name, mime, data):
        fields = dict(room_id=_storage_shared_1._identifier(room_id, label="room_id"), upload_id=_storage_shared_1._identifier(upload_id, label="upload_id"),
            kind=_storage_shared_1._kind(kind), name=_storage_shared_1._name(name), mime=_storage_shared_1._mime(mime))
        if not isinstance(data, bytes) or not data:
            raise _storage_shared_1.AttachmentError("attachment bytes must not be empty")
        if len(data) > _storage_shared_1.MAX_ATTACHMENT_BYTES:
            raise _storage_shared_1.AttachmentError("attachment exceeds the per-file size limit")
        _storage_shared_1._validate_mime_and_kind(data, kind=fields["kind"], mime=fields["mime"])
        fields.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data), catalog_name=_storage_shared_1.fold_catalog_text(fields["name"]))
        now = float(self.clock())
        self.prune(now=now)
        with files_gate(self.root):
            with self._store() as store, store.read() as conn:
                existing = repo.attachment(conn, store, room_id=fields["room_id"], upload_id=fields["upload_id"])
                old_blob = repo._blob_row(conn, store, sha256=fields["sha256"])
            if existing is not None:
                uploads.validate_retry(existing, fields)
                self._read_blob(blob_id=existing["blob_id"], size=existing["size"], sha256=existing["sha256"])
                return self._metadata(existing, idempotent=True)
            if old_blob is not None:
                self._read_blob(blob_id=old_blob["blob_id"], size=old_blob["size"], sha256=old_blob["sha256"])
            candidate = "blob_" + secrets.token_hex(16)
            fields["attachment_id"] = "att_" + secrets.token_hex(16)
            self._write_blob(self._blob_path(candidate), data)
            # Any exception, including a lost COMMIT ACK, leaves candidate bytes
            # for the store-lock-fenced sweep instead of guessing the outcome.
            limits = {key: getattr(self, key) for key in ("room_quota_bytes", "room_quota_count", "gateway_quota_bytes", "gateway_quota_count")}
            with self._store() as store:
                row, replayed = uploads.put(store, fields=fields, candidate_blob=candidate, now=now, limits=limits)
            if row["blob_id"] != candidate:
                self._blob_path(candidate).unlink(missing_ok=True)
            return self._metadata(row, idempotent=replayed)

    def find_upload(self, *, room_id, upload_id):
        room_id, upload_id = _storage_shared_1._identifier(room_id, label="room_id"), _storage_shared_1._identifier(upload_id, label="upload_id")
        now = float(self.clock())
        with self._store() as store:
            row = uploads.find_upload(store, room_id=room_id, upload_id=upload_id, now=now)
        if row is None:
            return None
        self._read_blob(blob_id=row["blob_id"], size=row["size"], sha256=row["sha256"])
        return self._metadata(row, idempotent=True)

    def commit_message_with_receipt(self, *, room_id, event_id, manifest, recipient_member_ids, viewer_access=False,
                                    retention_seconds=None, hold_until_event=False):
        room_id, event_id = _storage_shared_1._identifier(room_id, label="room_id"), _storage_shared_1._identifier(event_id, label="event_id")
        normalized = _storage_shared_1.validate_manifest(manifest)
        recipients = tuple(_storage_shared_1._identifier(member, label="recipient_member_id") for member in recipient_member_ids)
        if not recipients:
            raise _storage_shared_1.AttachmentError("attachment commitment requires recipient ids")
        if len(set(recipients)) != len(recipients):
            raise _storage_shared_1.AttachmentError("recipient ids must be unique")
        scope = dict(room_id=room_id, event_id=event_id, recipients_json=json.dumps(sorted(recipients), separators=(",", ":")),
            viewer_access=viewer_access, now=float(self.clock()))
        with files_gate(self.root):
            with self._store() as store:
                rows = commits.prepare(store, manifest=normalized, **scope)
            for row in rows:
                self._read_blob(blob_id=row["blob_id"], size=row["size"], sha256=row["sha256"])
            scope["now"] = float(self.clock())
            expires = scope["now"] + _storage_shared_1.UNCOMMITTED_TTL_SECONDS if hold_until_event else (
                None if retention_seconds is None else scope["now"] + float(retention_seconds))
            with self._store() as store:
                return commits.commit(store, manifest=normalized, expires_at=expires, **scope)

    def abort_message_commit(self, *, room_id, event_id, attachment_ids):
        room_id, event_id = _storage_shared_1._identifier(room_id, label="room_id"), _storage_shared_1._identifier(event_id, label="event_id")
        selected = [_storage_shared_1._attachment_id(value) for value in attachment_ids]
        now = float(self.clock())
        with self._store() as store:
            return commits.abort(store, room_id=room_id, event_id=event_id, attachment_ids=selected, now=now)

    def retain_event(self, *, room_id, event_id):
        room_id, event_id = _storage_shared_1._identifier(room_id, label="room_id"), _storage_shared_1._identifier(event_id, label="event_id")
        now = float(self.clock())
        with self._store() as store:
            return commits.retain_event(store, room_id=room_id, event_id=event_id, now=now)

    def reconcile_room_events(self):
        now = float(self.clock())
        with self._store() as store:
            return cleanup.reconcile(store, now)

    def mark_room_disbanded(self, room_id):
        room_id, now = _storage_shared_1._identifier(room_id, label="room_id"), float(self.clock())
        with self._store() as store:
            return cleanup.mark_disbanded(store, room_id, now)

    def prune(self, *, now=None):
        now = float(self.clock()) if now is None else float(now)
        with files_gate(self.root):
            with self._store() as store:
                removed = cleanup.prune(store, now=now, namespace=self.namespace)
            replay_cleanup(self)
            sweep_locked(self)
            return removed

    def _sweep_orphans(self):
        with files_gate(self.root):
            sweep_locked(self)

    def stats(self, *, room_id=None):
        with self._store() as store:
            return repo.stats(store, room_id)
