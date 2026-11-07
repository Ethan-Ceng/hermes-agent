"""Fresh-process attachment probe; every SQLite connection is a hard failure."""

import sqlite3
import sys

attempts = []


def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("SQLite connection rejected in PG attachment process")


sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == "sqlite3.connect" else None)

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore, AttachmentQuotaError

PNG = b"\x89PNG\r\n\x1a\nimage-payload"
role = sys.argv[1]
if role.startswith("quota-"):
    sys.stdin.readline()
    store = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100, room_quota_count=1)
    try:
        store.put(room_id="room", upload_id=role, kind="image", name="image.png", mime="image/png", data=PNG)
    except AttachmentQuotaError:
        print("QUOTA_REFUSED")
    else:
        print("QUOTA_ACCEPTED")
elif role == "read":
    store = HostedRoomAttachmentStore(rooms.default_db_path())
    saved = store.find_upload(room_id="room", upload_id="upload")
    assert saved is not None
    manifest = [{key: saved[key] for key in ("attachment_id", "kind", "name", "size", "mime")}]
    store.commit_message(room_id="room", event_id="event", manifest=manifest, recipient_member_ids=["ops"])
    assert store.read(room_id="room", attachment_id=saved["attachment_id"], event_id="event", recipient_member_id="ops").data == PNG
    print("PG_ATTACHMENT_RESTART_READ_OK")
elif role == "cleanup":
    store = HostedRoomAttachmentStore(rooms.default_db_path())
    assert store.stats()["attachments"] == 0 and store.stats()["blobs"] == 0
    assert not tuple(store.blob_root.iterdir())
    print("PG_ATTACHMENT_RESTART_CLEANUP_OK")
else:
    raise AssertionError("unknown attachment probe role")
assert not attempts
