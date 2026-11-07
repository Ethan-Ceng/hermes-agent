"""Supported byte formats, stable namespace and preservation of the SQLite dataset."""

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore, default_attachment_root, DISBANDED_GRACE_SECONDS
from tests.gateway.test_hosted_room_attachments import PNG, PDF, _manifest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize("kind,mime,name,data", [
    ("image", "image/png", "图片🙂.png", PNG),
    ("pdf", "application/pdf", "合同.pdf", PDF),
    ("file", "text/plain", "记录.txt", "UTF8实际文字🙂\n".encode()),
    ("file", "application/octet-stream", "opaque.bin", b"\x00\xff\x01\x00opaque"),
    ("file", "application/zip", "archive.zip", b"PK\x03\x04container"),
], ids=["image", "pdf", "utf8", "nul-binary", "zip"])
def test_real_pg_byte_round_trip_and_exact_metadata(pg_profiles, kind, mime, name, data):
    with pg_profiles("one"):
        store = HostedRoomAttachmentStore(rooms.default_db_path())
        saved = store.put(room_id="room", upload_id="upload", kind=kind, mime=mime, name=name, data=data)
        store.commit_message(room_id="room", event_id="event", manifest=_manifest(saved), recipient_member_ids=["ops"])
        read = HostedRoomAttachmentStore(store.db_path).read(room_id="room", event_id="event", attachment_id=saved["attachment_id"], recipient_member_id="ops")
        assert read.data == data and read.attachment["name"] == name and read.attachment["mime"] == mime
        assert read.attachment["size"] == len(data)


def test_pg_namespace_reopen_and_sweep_leave_old_sqlite_content_untouched(pg_profiles):
    with pg_profiles("one") as home:
        old = home / "hosted-room-attachments" / "blobs" / ("blob_" + "a" * 32)
        old.parent.mkdir(parents=True)
        old.write_bytes(b"untouched SQLite content")
        now = [100.0]
        location = rooms.default_db_path()
        store = HostedRoomAttachmentStore(location, clock=lambda: now[0])
        store.put(room_id="room", upload_id="upload", kind="image", mime="image/png", name="image.png", data=PNG)
        assert store.root == default_attachment_root(location)
        assert store.namespace == HostedRoomAttachmentStore(location, clock=lambda: now[0]).namespace
        assert store.root != old.parent.parent
        store.mark_room_disbanded("room")
        now[0] += DISBANDED_GRACE_SECONDS + 1
        assert store.prune() == 1 and store.stats()["blobs"] == 0
        assert old.read_bytes() == b"untouched SQLite content"
