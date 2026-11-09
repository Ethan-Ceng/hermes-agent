"""Durable, private attachment storage for gateway-owned Group Chats.

The room log carries only server-minted attachment ids and bounded metadata.
Canonical bytes live in a private directory beside ``state.db`` and are shared
by SHA-256 through an internal blob table.  Upload ids make client retries
idempotent; send-time commitment binds each upload to one room event and the
room's frozen recipient roster.
"""

from __future__ import annotations
from hermes_db.domains.rooms.attachments.files import AttachmentContent
from hermes_db.domains.rooms.attachments.rules import AttachmentConflictError, AttachmentData, AttachmentError, AttachmentIntegrityError, AttachmentNotFoundError, AttachmentQuotaError, DISBANDED_GRACE_SECONDS, MAX_ATTACHMENTS_PER_MESSAGE, MAX_ATTACHMENT_BYTES, MAX_ATTACHMENT_MIME_CHARS, MAX_ATTACHMENT_NAME_CHARS, MAX_GATEWAY_ATTACHMENT_COUNT, MAX_GATEWAY_BLOB_BYTES, MAX_IDENTIFIER_CHARS, MAX_MESSAGE_ATTACHMENT_BYTES, MAX_ROOM_ATTACHMENT_BYTES, MAX_ROOM_ATTACHMENT_COUNT, MAX_ROOM_UNCOMMITTED_BYTES, MAX_ROOM_UNCOMMITTED_COUNT, MAX_TASK_ATTACHMENTS, MAX_TASK_ATTACHMENT_BYTES, UNCOMMITTED_TTL_SECONDS, _BLOB_ID_RE, _attachment_id, _identifier, _kind, _mime, _name, _validate_mime_and_kind, fold_catalog_text, validate_manifest, validate_task_manifest

from hermes_db.domains.rooms.rules import EventAttachmentConflictError
from hermes_dir_acl import make_user_dir

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


CLASSIC_ATTACHMENT_TTL_SECONDS = 7 * 24 * 60 * 60

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
















def default_attachment_root(db_path: Path | str) -> Path:
    """Return the selected store's private byte root or persistent PG namespace."""
    from hermes_db.domains.rooms.api import is_postgresql_location
    if is_postgresql_location(db_path):
        return HostedRoomAttachmentStore(db_path).root
    return Path(db_path).parent / "hosted-room-attachments"














    # Generic files are opaque bytes. ZIP and gzip are container formats used
    # by many non-archive MIME types (DOCX, XLSX, PPTX, EPUB, JAR, APK, etc.).
    # Only image and PDF payloads are security-sensitive enough to require an
    # exact magic/MIME match here; text remains strict to avoid binary prompts.


def decode_content_base64(value: Any) -> bytes:
    """Strictly decode one bounded RPC upload body without accepting data URLs."""

    if not isinstance(value, str) or not value:
        raise AttachmentError("content_base64 is required")
    if value.lstrip().lower().startswith("data:"):
        raise AttachmentError("data URLs are not accepted")
    maximum_encoded = ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4
    if len(value) > maximum_encoded + 4:
        raise AttachmentError("attachment exceeds the per-file size limit")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentError("content_base64 is not valid base64") from exc
    if not data:
        raise AttachmentError("attachment must not be empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("attachment exceeds the per-file size limit")
    return data


def encode_content_base64(data: bytes) -> str:
    """Encode verified bytes for the bounded attachment read RPC."""

    return base64.b64encode(data).decode("ascii")








# (state.db, blob root) pairs whose schema, event reconciliation and prune already ran in this
# process. Callers build a store per operation (one per attachment chunk); startup work and
# its write locks must not repeat on every read.
_STARTED: set[tuple[str, str, int, int] | None] = set()
_STARTED_LOCK = threading.Lock()


class HostedRoomAttachmentStore(AttachmentContent):
    """Selected-backend metadata and private, content-deduplicated blob bytes."""

    def __new__(cls, db_path, **kwargs):
        from hermes_db.domains.rooms.api import is_postgresql_location
        if cls is HostedRoomAttachmentStore and is_postgresql_location(db_path):
            from hermes_db.integration.room_attachments import PostgresAttachmentStore
            return PostgresAttachmentStore(db_path, **kwargs)
        return super().__new__(cls)

    def __init__(
        self,
        db_path: Path | str,
        *,
        root: Path | str | None = None,
        clock: Callable[[], float] = time.time,
        room_quota_bytes: int = MAX_ROOM_ATTACHMENT_BYTES,
        gateway_quota_bytes: int = MAX_GATEWAY_BLOB_BYTES,
        room_quota_count: int = MAX_ROOM_ATTACHMENT_COUNT,
        gateway_quota_count: int = MAX_GATEWAY_ATTACHMENT_COUNT,
    ) -> None:
        self.db_path = Path(db_path)
        self.root = Path(root or default_attachment_root(self.db_path))
        self.blob_root = self.root / "blobs"
        self.clock = clock
        self.room_quota_bytes = max(1, int(room_quota_bytes))
        self.gateway_quota_bytes = max(1, int(gateway_quota_bytes))
        self.room_quota_count = max(1, int(room_quota_count))
        self.gateway_quota_count = max(1, int(gateway_quota_count))
        self._lock = threading.RLock()
        self._prepare_private_root()
        with _STARTED_LOCK:
            if self._startup_key() in _STARTED:
                return
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._initialize(conn)
                conn.commit()
            finally:
                conn.close()
            self.reconcile_room_events()
            self.prune()
            _STARTED.add(self._startup_key())

    def _startup_key(self) -> tuple[str, str, int, int] | None:
        """Identity of the database FILE, so a recreated state.db is set up again."""
        try:
            info = self.db_path.stat()
        except OSError:
            return None
        return str(self.db_path.resolve()), str(self.root.resolve()), info.st_dev, info.st_ino


    def _initialize(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hosted_room_attachment_blobs (
                blob_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL UNIQUE,
                size INTEGER NOT NULL CHECK (size > 0),
                ref_count INTEGER NOT NULL CHECK (ref_count > 0),
                created_at REAL NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hosted_room_attachments (
                attachment_id TEXT PRIMARY KEY,
                upload_id TEXT NOT NULL,
                room_id TEXT NOT NULL,
                event_id TEXT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                size INTEGER NOT NULL CHECK (size > 0),
                mime TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                blob_id TEXT NOT NULL,
                recipient_member_ids_json TEXT NOT NULL DEFAULT '[]',
                viewer_access INTEGER NOT NULL DEFAULT 0 CHECK (viewer_access IN (0, 1)),
                state TEXT NOT NULL CHECK (state IN ('uploaded', 'committed', 'disbanded')),
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL,
                UNIQUE (room_id, upload_id),
                FOREIGN KEY (blob_id) REFERENCES hosted_room_attachment_blobs(blob_id)
            )"""
        )
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(hosted_room_attachments)")
        }
        if "viewer_access" not in columns:
            conn.execute(
                """ALTER TABLE hosted_room_attachments
                   ADD COLUMN viewer_access INTEGER NOT NULL DEFAULT 0"""
            )
        if "catalog_name" not in columns:
            conn.execute("ALTER TABLE hosted_room_attachments ADD COLUMN catalog_name TEXT")
            reader = conn.execute("SELECT attachment_id, name FROM hosted_room_attachments")
            while rows := reader.fetchmany(512):
                conn.executemany(
                    "UPDATE hosted_room_attachments SET catalog_name=? WHERE attachment_id=?",
                    ((fold_catalog_text(str(row["name"])), row["attachment_id"]) for row in rows),
                )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_room_attachments_room_state
               ON hosted_room_attachments(room_id, state, created_at)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_room_attachments_expiry
               ON hosted_room_attachments(expires_at)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_hosted_room_attachments_event
               ON hosted_room_attachments(room_id, event_id)"""
        )

    def _connect(self) -> sqlite3.Connection:
        from hermes_db.domains.rooms.api import assert_sqlite_location
        assert_sqlite_location(self.db_path)
        from hermes_state_wal import apply_wal_with_fallback

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            apply_wal_with_fallback(conn, db_label="state.db (hosted room attachments)")
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            conn.close()
            raise
        return conn

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()







    def put(
        self,
        *,
        room_id: Any,
        upload_id: Any,
        kind: Any,
        name: Any,
        mime: Any,
        data: bytes,
    ) -> dict[str, Any]:
        room_id = _identifier(room_id, label="room_id")
        upload_id = _identifier(upload_id, label="upload_id")
        kind = _kind(kind)
        name = _name(name)
        mime = _mime(mime)
        if not isinstance(data, bytes) or not data:
            raise AttachmentError("attachment bytes must not be empty")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise AttachmentError("attachment exceeds the per-file size limit")
        _validate_mime_and_kind(data, kind=kind, mime=mime)
        digest = hashlib.sha256(data).hexdigest()
        now = float(self.clock())
        # Long-lived gateways keep one store instance. Reclaim abandoned
        # uploads before applying quotas so an expired failed send cannot
        # permanently exhaust the room without a process restart.
        self.prune(now=now)

        with self._lock, self._transaction(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM hosted_room_attachments WHERE room_id=? AND upload_id=?",
                (room_id, upload_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["kind"]) != kind
                    or str(existing["name"]) != name
                    or str(existing["mime"]) != mime
                    or int(existing["size"]) != len(data)
                    or str(existing["sha256"]) != digest
                ):
                    raise AttachmentConflictError(
                        "upload_id was already used for different attachment content"
                    )
                self._read_blob(
                    blob_id=str(existing["blob_id"]),
                    size=int(existing["size"]),
                    sha256=str(existing["sha256"]),
                )
                return self._metadata(existing, idempotent=True)

            room_totals = conn.execute(
                """SELECT COALESCE(SUM(size), 0) AS bytes, COUNT(*) AS count
                     FROM hosted_room_attachments
                    WHERE room_id=? AND state!='disbanded'""",
                (room_id,),
            ).fetchone()
            uncommitted = conn.execute(
                """SELECT COALESCE(SUM(size), 0) AS bytes, COUNT(*) AS count
                     FROM hosted_room_attachments
                    WHERE room_id=? AND state='uploaded'""",
                (room_id,),
            ).fetchone()
            if int(room_totals["bytes"]) + len(data) > self.room_quota_bytes:
                raise AttachmentQuotaError("room attachment quota exceeded")
            if int(room_totals["count"]) >= self.room_quota_count:
                raise AttachmentQuotaError("room attachment count quota exceeded")
            total_count = int(conn.execute("SELECT COUNT(*) FROM hosted_room_attachments").fetchone()[0])
            if total_count >= self.gateway_quota_count:
                raise AttachmentQuotaError("gateway attachment count quota exceeded")
            if (
                int(uncommitted["bytes"]) + len(data) > MAX_ROOM_UNCOMMITTED_BYTES
                or int(uncommitted["count"]) + 1 > MAX_ROOM_UNCOMMITTED_COUNT
            ):
                raise AttachmentQuotaError("room uncommitted upload quota exceeded")

            blob = conn.execute(
                "SELECT * FROM hosted_room_attachment_blobs WHERE sha256=?",
                (digest,),
            ).fetchone()
            if blob is None:
                physical = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(size), 0) FROM hosted_room_attachment_blobs"
                    ).fetchone()[0]
                )
                if physical + len(data) > self.gateway_quota_bytes:
                    raise AttachmentQuotaError("gateway attachment quota exceeded")
                blob_id = f"blob_{secrets.token_hex(16)}"
                target = self._blob_path(blob_id)
                self._write_blob(target, data)
                conn.execute(
                    """INSERT INTO hosted_room_attachment_blobs
                       (blob_id, sha256, size, ref_count, created_at)
                       VALUES (?, ?, ?, 1, ?)""",
                    (blob_id, digest, len(data), now),
                )
            else:
                blob_id = str(blob["blob_id"])
                self._read_blob(blob_id=blob_id, size=int(blob["size"]), sha256=digest)
                conn.execute(
                    "UPDATE hosted_room_attachment_blobs SET ref_count=ref_count+1 WHERE blob_id=?",
                    (blob_id,),
                )

            attachment_id = f"att_{secrets.token_hex(16)}"
            conn.execute(
                """INSERT INTO hosted_room_attachments
                   (attachment_id, upload_id, room_id, event_id, kind, name, catalog_name, size,
                    mime, sha256, blob_id, recipient_member_ids_json, state,
                    created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, '[]', 'uploaded', ?, ?, ?)""",
                (
                    attachment_id,
                    upload_id,
                    room_id,
                    kind,
                    name,
                    fold_catalog_text(name),
                    len(data),
                    mime,
                    digest,
                    blob_id,
                    now,
                    now,
                    now + UNCOMMITTED_TTL_SECONDS,
                ),
            )
            row = conn.execute(
                "SELECT * FROM hosted_room_attachments WHERE attachment_id=?",
                (attachment_id,),
            ).fetchone()
            if row is None:  # pragma: no cover - guarded by insert
                raise RuntimeError("stored attachment could not be reloaded")
            return self._metadata(row)

    def find_upload(self, *, room_id: Any, upload_id: Any) -> dict[str, Any] | None:
        """Return verified metadata for an idempotent upload retry, if it exists."""

        room_id = _identifier(room_id, label="room_id")
        upload_id = _identifier(upload_id, label="upload_id")
        now = float(self.clock())
        with self._transaction() as conn:
            row = conn.execute(
                """SELECT * FROM hosted_room_attachments
                    WHERE room_id=? AND upload_id=?""",
                (room_id, upload_id),
            ).fetchone()
            if row is None or str(row["state"]) == "disbanded":
                return None
            if row["expires_at"] is not None and float(row["expires_at"]) <= now:
                return None
            self._read_blob(
                blob_id=str(row["blob_id"]),
                size=int(row["size"]),
                sha256=str(row["sha256"]),
            )
            return self._metadata(row, idempotent=True)


    def commit_message_with_receipt(
        self,
        *,
        room_id: Any,
        event_id: Any,
        manifest: Any,
        recipient_member_ids: Sequence[str],
        viewer_access: bool = False,
        retention_seconds: float | None = None,
        hold_until_event: bool = False,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        """Commit a manifest and report only rows transitioned by this call."""

        room_id = _identifier(room_id, label="room_id")
        event_id = _identifier(event_id, label="event_id")
        normalized = validate_manifest(manifest)
        recipients = tuple(
            _identifier(member_id, label="recipient_member_id")
            for member_id in recipient_member_ids
        )
        if not recipients:
            raise AttachmentError("attachment commitment requires recipient ids")
        if len(set(recipients)) != len(recipients):
            raise AttachmentError("recipient ids must be unique")
        recipients_json = json.dumps(sorted(recipients), separators=(",", ":"))
        now = float(self.clock())
        expires_at = (
            now + UNCOMMITTED_TTL_SECONDS
            if hold_until_event
            else None
            if retention_seconds is None
            else now + float(retention_seconds)
        )

        transitioned: list[str] = []
        with self._lock, self._transaction(immediate=True) as conn:
            for entry in normalized:
                row = conn.execute(
                    "SELECT * FROM hosted_room_attachments WHERE attachment_id=?",
                    (entry["attachment_id"],),
                ).fetchone()
                if row is None or str(row["room_id"]) != room_id:
                    raise AttachmentNotFoundError("attachment is not uploaded for this room")
                durable = {
                    "attachment_id": str(row["attachment_id"]),
                    "kind": str(row["kind"]),
                    "name": str(row["name"]),
                    "size": int(row["size"]),
                    "mime": str(row["mime"]),
                }
                if durable != entry:
                    raise AttachmentConflictError(
                        "attachment manifest metadata does not match the uploaded bytes"
                    )
                if row["expires_at"] is not None and float(row["expires_at"]) <= now:
                    raise AttachmentNotFoundError("attachment has expired")
                state = str(row["state"])
                if state == "disbanded":
                    raise AttachmentNotFoundError("attachment belongs to a disbanded room")
                if state == "committed" and (
                    str(row["event_id"] or "") != event_id
                    or str(row["recipient_member_ids_json"]) != recipients_json
                    or bool(row["viewer_access"]) != bool(viewer_access)
                ):
                    raise AttachmentConflictError(
                        "attachment is already owned by a different room event"
                    )
                if state == "uploaded":
                    transitioned.append(entry["attachment_id"])
                self._read_blob(
                    blob_id=str(row["blob_id"]),
                    size=int(row["size"]),
                    sha256=str(row["sha256"]),
                )
            for entry in normalized:
                if entry["attachment_id"] not in transitioned:
                    continue
                updated = conn.execute(
                    """UPDATE hosted_room_attachments
                          SET event_id=?, recipient_member_ids_json=?, viewer_access=?, state='committed',
                              updated_at=?, expires_at=?
                        WHERE attachment_id=? AND state='uploaded'""",
                    (
                        event_id,
                        recipients_json,
                        1 if viewer_access else 0,
                        now,
                        expires_at,
                        entry["attachment_id"],
                    ),
                )
                if updated.rowcount != 1:
                    raise AttachmentConflictError(
                        "attachment changed during message commitment"
                    )
        return normalized, tuple(transitioned)

    def abort_message_commit(
        self,
        *,
        room_id: Any,
        event_id: Any,
        attachment_ids: Sequence[str],
    ) -> int:
        """Return a failed pre-event commitment to its bounded upload state."""

        room_id = _identifier(room_id, label="room_id")
        event_id = _identifier(event_id, label="event_id")
        attachment_ids = [_attachment_id(value) for value in attachment_ids]
        if not attachment_ids:
            return 0
        now = float(self.clock())
        with self._transaction(immediate=True) as conn:
            owner = _owner_event(conn, room_id, event_id)
            if owner is not None:
                published_ids = {
                    item.get("attachment_id")
                    for item in json.loads(owner["payload_json"]).get("attachments", [])
                    if isinstance(item, Mapping)
                }
                attachment_ids = [
                    value for value in attachment_ids if value not in published_ids
                ]
            if not attachment_ids:
                return 0
            placeholders = ",".join("?" for _ in attachment_ids)
            changed = conn.execute(
                f"""UPDATE hosted_room_attachments
                        SET event_id=NULL, recipient_member_ids_json='[]', viewer_access=0,
                            state='uploaded', updated_at=?, expires_at=?
                      WHERE room_id=? AND event_id=? AND state='committed'
                        AND attachment_id IN ({placeholders})""",
                (
                    now,
                    now + UNCOMMITTED_TTL_SECONDS,
                    room_id,
                    event_id,
                    *attachment_ids,
                ),
            )
            return int(changed.rowcount)

    def retain_event(self, *, room_id: Any, event_id: Any) -> int:
        """Retain committed blobs after their immutable room event is durable."""

        room_id = _identifier(room_id, label="room_id")
        event_id = _identifier(event_id, label="event_id")
        now = float(self.clock())
        with self._transaction(immediate=True) as conn:
            event = conn.execute(
                """SELECT 1 FROM hosted_room_events
                    WHERE room_id=? AND event_id=? LIMIT 1""",
                (room_id, event_id),
            ).fetchone()
            if event is None:
                raise AttachmentConflictError(
                    "attachment owner event is not durable in the room log"
                )
            changed = conn.execute(
                """UPDATE hosted_room_attachments
                      SET expires_at=NULL, updated_at=?
                    WHERE room_id=? AND event_id=? AND state='committed'""",
                (now, room_id, event_id),
            )
            return int(changed.rowcount)

    def read(
        self,
        *,
        room_id: Any,
        attachment_id: Any,
        recipient_member_id: Any,
        event_id: Any | None = None,
        viewer: bool = False,
    ) -> AttachmentData:
        room_id = _identifier(room_id, label="room_id")
        attachment_id = _attachment_id(attachment_id)
        recipient_member_id = (
            _identifier(recipient_member_id, label="recipient_member_id")
            if recipient_member_id is not None
            else ""
        )
        normalized_event = _identifier(event_id, label="event_id") if event_id is not None else None
        now = float(self.clock())
        with self._transaction() as conn:
            row = self._read_committed_row(
                conn, room_id=room_id, attachment_id=attachment_id,
                recipient_member_id=recipient_member_id,
                normalized_event=normalized_event, viewer=viewer, now=now,
            )
            data = self._read_blob(
                blob_id=str(row["blob_id"]),
                size=int(row["size"]),
                sha256=str(row["sha256"]),
            )
            return AttachmentData(self._metadata(row), data)

    def describe(
        self,
        *,
        room_id: Any,
        attachment_id: Any,
        recipient_member_id: Any,
        event_id: Any,
    ) -> dict[str, Any]:
        """``read`` without bytes: the metadata (including the upload-verified SHA-256) of a
        committed attachment this recipient may read for this event."""
        room_id = _identifier(room_id, label="room_id")
        attachment_id = _attachment_id(attachment_id)
        recipient_member_id = _identifier(recipient_member_id, label="recipient_member_id")
        normalized_event = _identifier(event_id, label="event_id")
        with self._transaction() as conn:
            row = self._read_committed_row(
                conn, room_id=room_id, attachment_id=attachment_id,
                recipient_member_id=recipient_member_id,
                normalized_event=normalized_event, viewer=False, now=float(self.clock()),
            )
            return self._metadata(row)

    def read_range(
        self,
        *,
        room_id: Any,
        attachment_id: Any,
        recipient_member_id: Any,
        event_id: Any,
        offset: int,
        length: int,
    ) -> AttachmentData:
        """``read`` for one slice: same authorization, metadata carries the stored whole-file
        SHA-256 and the receiver verifies the reassembled bytes against it."""
        room_id = _identifier(room_id, label="room_id")
        attachment_id = _attachment_id(attachment_id)
        recipient_member_id = _identifier(recipient_member_id, label="recipient_member_id")
        normalized_event = _identifier(event_id, label="event_id")
        if type(offset) is not int or type(length) is not int or offset < 0 or length <= 0:
            raise AttachmentError("attachment range must be non-negative integers")
        with self._transaction() as conn:
            row = self._read_committed_row(
                conn, room_id=room_id, attachment_id=attachment_id,
                recipient_member_id=recipient_member_id,
                normalized_event=normalized_event, viewer=False, now=float(self.clock()),
            )
            if offset >= int(row["size"]):
                raise AttachmentError("attachment range starts past the end")
            data = self._read_blob_range(
                blob_id=str(row["blob_id"]), size=int(row["size"]), offset=offset, length=length)
            return AttachmentData(self._metadata(row), data)

    def reconcile_room_events(self) -> int:
        """Recover only attachment commitments named by the durable event payload."""

        changed = 0
        now = float(self.clock())
        with self._transaction(immediate=True) as conn:
            has_events = conn.execute(
                """SELECT 1 FROM sqlite_master
                    WHERE type='table' AND name='hosted_room_events'"""
            ).fetchone()
            if has_events is None:
                return 0
            rows = conn.execute(
                """SELECT attachment.attachment_id, attachment.event_id,
                          event.payload_json
                     FROM hosted_room_attachments AS attachment
                     JOIN hosted_room_events AS event
                       ON event.room_id=attachment.room_id
                      AND event.event_id=attachment.event_id
                    WHERE attachment.state='committed'
                      AND attachment.expires_at IS NOT NULL"""
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(str(row["payload_json"]))
                    ids = {
                        str(item.get("attachment_id") or "")
                        for item in payload.get("attachments", [])
                        if isinstance(item, Mapping)
                    }
                # Malformed row: bad/over-nested JSON, a non-object payload, or non-iterable attachments.
                except (ValueError, TypeError, AttributeError, RecursionError):
                    continue
                if str(row["attachment_id"]) not in ids:
                    continue
                changed += conn.execute(
                    """UPDATE hosted_room_attachments
                          SET expires_at=NULL, updated_at=?
                        WHERE attachment_id=? AND state='committed'""",
                    (now, str(row["attachment_id"])),
                ).rowcount
        return int(changed)

    def mark_room_disbanded(self, room_id: Any) -> int:
        room_id = _identifier(room_id, label="room_id")
        now = float(self.clock())
        with self._transaction(immediate=True) as conn:
            changed = conn.execute(
                """UPDATE hosted_room_attachments
                      SET state='disbanded', updated_at=?, expires_at=?
                    WHERE room_id=? AND state!='disbanded'""",
                (now, now + DISBANDED_GRACE_SECONDS, room_id),
            )
            return int(changed.rowcount)

    def prune(self, *, now: float | None = None) -> int:
        now = float(self.clock()) if now is None else float(now)
        removed_blob_ids: list[str] = []
        removed = 0
        with self._lock, self._transaction(immediate=True) as conn:
            has_rooms = conn.execute(
                """SELECT 1 FROM sqlite_master
                    WHERE type='table' AND name='hosted_rooms'"""
            ).fetchone()
            if has_rooms is not None:
                conn.execute(
                    """UPDATE hosted_room_attachments
                          SET state='disbanded',
                              expires_at=(
                                SELECT room.disbanded_at + ? FROM hosted_rooms AS room
                                 WHERE room.room_id=hosted_room_attachments.room_id
                              ),
                              updated_at=?
                        WHERE state='committed' AND EXISTS (
                            SELECT 1 FROM hosted_rooms AS room
                             WHERE room.room_id=hosted_room_attachments.room_id
                               AND room.disbanded_at IS NOT NULL
                        )""",
                    (DISBANDED_GRACE_SECONDS, now),
                )
            rows = conn.execute(
                """SELECT attachment_id, blob_id FROM hosted_room_attachments
                    WHERE expires_at IS NOT NULL AND expires_at <= ?""",
                (now,),
            ).fetchall()
            released = Counter(str(row["blob_id"]) for row in rows)
            for row in rows:
                conn.execute(
                    "DELETE FROM hosted_room_attachments WHERE attachment_id=?",
                    (str(row["attachment_id"]),),
                )
                removed += 1
            for blob_id, count in released.items():
                blob = conn.execute(
                    "SELECT ref_count FROM hosted_room_attachment_blobs WHERE blob_id=?",
                    (blob_id,),
                ).fetchone()
                if blob is None:
                    continue
                if int(blob["ref_count"]) <= count:
                    removed_blob_ids.append(blob_id)
                else:
                    conn.execute(
                        """UPDATE hosted_room_attachment_blobs
                              SET ref_count=ref_count-?
                            WHERE blob_id=?""",
                        (count, blob_id),
                    )
            if removed_blob_ids:
                conn.executemany(
                    "DELETE FROM hosted_room_attachment_blobs WHERE blob_id=?",
                    ((blob_id,) for blob_id in removed_blob_ids),
                )
        for blob_id in removed_blob_ids:
            self._blob_path(blob_id).unlink(missing_ok=True)
        self._sweep_orphans()
        return removed

    def _sweep_orphans(self) -> None:
        quarantined: list[Path] = []
        with self._lock:
            try:
                candidates = tuple(self.blob_root.iterdir())
            except OSError:
                return
            with self._transaction(immediate=True) as conn:
                live = {
                    str(row["blob_id"])
                    for row in conn.execute(
                        "SELECT blob_id FROM hosted_room_attachment_blobs"
                    )
                }
                for index, path in enumerate(candidates):
                    if not (
                        path.name.startswith((".tmp-", ".prune-"))
                        or (
                            _BLOB_ID_RE.fullmatch(path.name) is not None
                            and path.name not in live
                        )
                    ):
                        continue
                    quarantine = self.blob_root / (
                        f".prune-{os.getpid()}-{threading.get_ident()}-"
                        f"{time.time_ns()}-{index}"
                    )
                    try:
                        os.replace(path, quarantine)
                    except OSError:
                        continue
                    quarantined.append(quarantine)
            # Renaming while the write transaction is active is the atomic
            # reference fence; unlinking the private quarantine can be slow and
            # therefore happens only after SQLite has committed.
            for path in quarantined:
                path.unlink(missing_ok=True)

    def stats(self, *, room_id: str | None = None) -> dict[str, int]:
        with self._transaction() as conn:
            where = " WHERE room_id=?" if room_id is not None else ""
            params = (room_id,) if room_id is not None else ()
            row = conn.execute(
                f"SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS bytes "
                f"FROM hosted_room_attachments{where}",
                params,
            ).fetchone()
            blob = conn.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS bytes "
                "FROM hosted_room_attachment_blobs"
            ).fetchone()
        return {
            "attachments": int(row["count"]),
            "logical_bytes": int(row["bytes"]),
            "blobs": int(blob["count"]),
            "physical_bytes": int(blob["bytes"]),
        }


    def read_viewer(
        self,
        *,
        room_id: Any,
        attachment_id: Any,
        event_id: Any | None = None,
        recipient_member_id: Any = None,
        authority_gateway_id: Any,
        authority_epoch: Any,
    ) -> AttachmentData:
        """Read for a live hosted viewer, fencing revocation across byte I/O."""

        room_id = _identifier(room_id, label="room_id")
        attachment_id = _attachment_id(attachment_id)
        normalized_event = _identifier(event_id, label="event_id") if event_id is not None else None
        recipient_member_id = (
            _identifier(recipient_member_id, label="recipient_member_id")
            if recipient_member_id is not None else ""
        )
        authority_gateway_id = _identifier(authority_gateway_id, label="authority_gateway_id")
        if isinstance(authority_epoch, bool) or not isinstance(authority_epoch, int) or authority_epoch < 1:
            raise AttachmentError("authority_epoch must be a positive integer")
        scope = {
            "room_id": room_id,
            "authority_gateway_id": authority_gateway_id,
            "authority_epoch": authority_epoch,
        }
        selection = {
            "room_id": room_id,
            "attachment_id": attachment_id,
            "recipient_member_id": recipient_member_id,
            "normalized_event": normalized_event,
            "viewer": True,
        }
        with self._transaction() as conn:
            conn.execute("BEGIN")
            self._require_viewer_room(conn, **scope)
            row = self._read_committed_row(conn, **selection, now=float(self.clock()))

        # No execution lock or SQLite snapshot spans filesystem/hash work.
        data = self._read_blob(
            blob_id=str(row["blob_id"]), size=int(row["size"]), sha256=str(row["sha256"]),
        )
        with self._transaction() as conn:
            conn.execute("BEGIN")
            self._require_viewer_room(conn, **scope)
            current = self._read_committed_row(conn, **selection, now=float(self.clock()))
            if current["blob_id"] != row["blob_id"] or self._metadata(current) != self._metadata(row):
                raise AttachmentNotFoundError("attachment changed during viewer read")
        return AttachmentData(self._metadata(current), data)


    @staticmethod
    def _require_viewer_room(
        conn: sqlite3.Connection,
        *,
        room_id: str,
        authority_gateway_id: str,
        authority_epoch: int,
    ) -> None:
        from gateway.hosted_rooms_common import table_exists as _table_exists

        if not _table_exists(conn, "hosted_rooms"):
            raise AttachmentNotFoundError("Group Chat is unavailable to viewers")
        room = conn.execute(
            """SELECT authority_gateway_id, authority_epoch, disbanded_at
               FROM hosted_rooms WHERE room_id=?""",
            (room_id,),
        ).fetchone()
        if (
            room is None
            or room["disbanded_at"] is not None
            or room["authority_gateway_id"] != authority_gateway_id
            or room["authority_epoch"] != authority_epoch
        ):
            raise AttachmentNotFoundError("Group Chat viewer authority changed")
        # Files-only sources need not install the optional safety/retirement schema.
        for table in ("hosted_room_quarantine", "hosted_room_disband_fences"):
            if _table_exists(conn, table) and conn.execute(
                f"SELECT 1 FROM {table} WHERE room_id=?", (room_id,),
            ).fetchone() is not None:
                raise AttachmentNotFoundError("Group Chat is unavailable to viewers")


    @staticmethod
    def _read_committed_row(
        conn: sqlite3.Connection,
        *,
        room_id: str,
        attachment_id: str,
        recipient_member_id: str,
        normalized_event: str | None,
        viewer: bool,
        now: float,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM hosted_room_attachments WHERE attachment_id=? AND room_id=?",
            (attachment_id, room_id),
        ).fetchone()
        if row is None or str(row["state"]) != "committed":
            raise AttachmentNotFoundError("attachment is not committed for this room")
        if row["expires_at"] is not None and float(row["expires_at"]) <= now:
            raise AttachmentNotFoundError("attachment has expired")
        if normalized_event is not None and str(row["event_id"] or "") != normalized_event:
            raise AttachmentNotFoundError("attachment is not owned by this room event")
        if int(row["viewer_access"] or 0):
            # Room-visible files need a published owner even for member reads.
            # A pre-event commitment is staging, not authority to expose bytes.
            if (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_room_events'"
                ).fetchone()
                is None
            ):
                raise AttachmentNotFoundError(
                    "attachment is not published in this room"
                )
            owner = conn.execute(
                """SELECT payload_json FROM hosted_room_events
                       WHERE room_id=? AND event_id=? AND kind IN ('message.user', 'message.member')""",
                (room_id, str(row["event_id"] or "")),
            ).fetchone()
            manifest = {
                key: row[key]
                for key in ("attachment_id", "kind", "name", "size", "mime")
            }
            payload = (
                json.loads(owner["payload_json"]) if owner is not None else None
            )
            published = (
                payload.get("attachments") if isinstance(payload, Mapping) else None
            )
            if not isinstance(published, list) or manifest not in published:
                raise AttachmentNotFoundError(
                    "attachment is not published in this room"
                )
        recipients = json.loads(str(row["recipient_member_ids_json"]))
        if viewer:
            if int(row["viewer_access"] or 0) != 1:
                raise AttachmentNotFoundError(
                    "attachment is unavailable to Group Chat viewers"
                )
        elif recipient_member_id not in recipients:
            raise AttachmentNotFoundError("attachment is unavailable to this recipient")
        return row




__all__ = [
    "CLASSIC_ATTACHMENT_TTL_SECONDS",
    "DISBANDED_GRACE_SECONDS",
    "MAX_ATTACHMENTS_PER_MESSAGE",
    "MAX_ATTACHMENT_BYTES",
    "MAX_MESSAGE_ATTACHMENT_BYTES",
    "MAX_TASK_ATTACHMENTS",
    "MAX_TASK_ATTACHMENT_BYTES",
    "UNCOMMITTED_TTL_SECONDS",
    "AttachmentConflictError",
    "AttachmentData",
    "AttachmentError",
    "AttachmentIntegrityError",
    "AttachmentNotFoundError",
    "AttachmentQuotaError",
    "HostedRoomAttachmentStore",
    "decode_content_base64",
    "default_attachment_root",
    "encode_content_base64",
    "validate_manifest",
    "validate_task_manifest",
]


def _owner_event(
    conn: sqlite3.Connection, room_id: str, event_id: str
) -> sqlite3.Row | None:
    # The standalone private-transport store need not have a canonical room log.
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_room_events'"
        ).fetchone()
        is None
    ):
        return None
    return conn.execute(
        "SELECT payload_json FROM hosted_room_events WHERE room_id=? AND event_id=?",
        (room_id, event_id),
    ).fetchone()


def retain_message_attachments(
    conn: sqlite3.Connection,
    *,
    room_id: str,
    event_id: str,
    manifest: Any,
    now: float,
) -> None:
    """Validate and retain exact commitments inside the canonical append transaction."""

    normalized = validate_manifest(manifest)
    if not normalized:
        return
    if normalized != manifest:
        raise AttachmentError("published attachment metadata must be canonical")
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_room_attachments'"
        ).fetchone()
        is None
    ):
        raise EventAttachmentConflictError("message attachments are not committed")
    for entry in normalized:
        row = conn.execute(
            "SELECT * FROM hosted_room_attachments WHERE attachment_id=?",
            (entry["attachment_id"],),
        ).fetchone()
        if (
            row is None
            or row["room_id"] != room_id
            or row["event_id"] != event_id
            or row["state"] != "committed"
            or row["viewer_access"] != 1
            or (row["expires_at"] is not None and float(row["expires_at"]) <= now)
            or any(row[key] != value for key, value in entry.items())
        ):
            raise EventAttachmentConflictError(
                "attachment commitment changed before event publication"
            )
    # Rollback and expiry use the same SQL write lock. No byte or peer I/O is
    # needed here; import verified the bytes before staging these commitments.
    conn.executemany(
        """UPDATE hosted_room_attachments SET expires_at=NULL, updated_at=?
           WHERE attachment_id=?""",
        ((now, entry["attachment_id"]) for entry in normalized),
    )
