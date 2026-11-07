"""Real PG attachment metadata with private files and no SQLite connections."""

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore, AttachmentConflictError
from tests.gateway.test_hosted_room_attachments import PNG, _manifest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_pg_attachment_persistence_deduplication_commit_and_scope(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        store = HostedRoomAttachmentStore(location)
        args = dict(room_id="room", upload_id="upload", kind="image", name="示意🙂.png", mime="image/png", data=PNG)
        first = store.put(**args)
        assert store.put(**args)["idempotent"]
        second = store.put(**(args | {"upload_id": "second"}))
        assert second["attachment_id"] != first["attachment_id"]
        assert store.stats() == dict(attachments=2, logical_bytes=2 * len(PNG), blobs=1, physical_bytes=len(PNG))
        with pytest.raises(AttachmentConflictError):
            store.put(**(args | {"name": "different.png"}))
        store.commit_message(room_id="room", event_id="event", manifest=_manifest(first), recipient_member_ids=["ops"])
        reopened = HostedRoomAttachmentStore(location)
        assert reopened.read(room_id="room", attachment_id=first["attachment_id"], event_id="event", recipient_member_id="ops").data == PNG
        assert reopened.find_upload(room_id="room", upload_id="upload")["attachment_id"] == first["attachment_id"]
    with pg_profiles("two"):
        assert HostedRoomAttachmentStore(rooms.default_db_path()).stats()["attachments"] == 0


def test_nonempty_attachment_publication_retains_commit_in_same_event_transaction(pg_profiles):
    from gateway.hosted_room_attachments import AttachmentNotFoundError
    with pg_profiles("one"):
        location = rooms.default_db_path()
        rooms.create_room(location, room_id="room", name="Room", members=[dict(member_id="ops", profile="ops", handle="ops")], authority_gateway_id="owner")
        store = HostedRoomAttachmentStore(location)
        saved = store.put(room_id="room", upload_id="upload", kind="image", name="image.png", mime="image/png", data=PNG)
        manifest = _manifest(saved)
        store.commit_message(room_id="room", event_id="event", manifest=manifest, recipient_member_ids=["ops"], viewer_access=True, hold_until_event=True)
        proof = dict(room_id="room", attachment_id=saved["attachment_id"], event_id="event", authority_gateway_id="owner", authority_epoch=1)
        with pytest.raises(AttachmentNotFoundError):
            store.read_viewer(**proof)
        event = rooms.append_event(location, room_id="room", event_id="event", kind="message.user", actor={"kind": "user", "id": "alice"},
            payload=dict(text="image", attachments=manifest), authority_gateway_id="owner", authority_epoch=1)
        assert store.read_viewer(**proof).data == PNG
        assert store.abort_message_commit(room_id="room", event_id="event", attachment_ids=[saved["attachment_id"]]) == 0
        assert rooms.read_events(location, room_id="room")["events"][0]["payload"]["attachments"] == manifest
        assert event["seq"] == 1
