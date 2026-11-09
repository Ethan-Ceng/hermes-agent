"""Actual PG event rollback, revocation across byte IO and integrity/range guards."""

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore, AttachmentNotFoundError, AttachmentIntegrityError
from tests.gateway.test_hosted_room_attachments import PNG, _manifest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def published(location):
    rooms.create_room(location, room_id="room", name="Room", members=[dict(member_id="ops", profile="ops", handle="ops")], authority_gateway_id="owner")
    store = HostedRoomAttachmentStore(location)
    saved = store.put(room_id="room", upload_id="upload", kind="image", name="image.png", mime="image/png", data=PNG)
    manifest = _manifest(saved)
    store.commit_message(room_id="room", event_id="event", manifest=manifest, recipient_member_ids=["ops"], viewer_access=True, hold_until_event=True)
    return store, saved, manifest


def append(location, manifest):
    return rooms.append_event(location, room_id="room", event_id="event", kind="message.user", actor={"kind": "user", "id": "alice"},
        payload=dict(text="image", attachments=manifest), authority_gateway_id="owner", authority_epoch=1)


def test_failed_event_rolls_back_retention_and_abort_releases_only_unpublished_commit(pg_profiles, monkeypatch):
    from sqlalchemy import select
    from hermes_db.domains.rooms.api import open_room_store
    from hermes_db.tables.room_attachments import attachments
    with pg_profiles("one"):
        location = rooms.default_db_path()
        store, saved, manifest = published(location)
        with monkeypatch.context() as patch:
            patch.setattr(rooms, "MAX_EVENTS_PER_ROOM", 0)
            with pytest.raises(rooms.HostedRoomError):
                append(location, manifest)
        with open_room_store(location) as resource, resource.read() as conn:
            assert conn.scalar(select(attachments.c.expires_at).where(attachments.c.store_id == resource.scope.store_id,
                attachments.c.attachment_id == saved["attachment_id"])) is not None
        assert rooms.read_events(location, room_id="room")["latest_seq"] == 0
        assert store.abort_message_commit(room_id="room", event_id="event", attachment_ids=[saved["attachment_id"]]) == 1
        with pytest.raises(AttachmentNotFoundError):
            store.read(room_id="room", attachment_id=saved["attachment_id"], recipient_member_id="ops", event_id="event")


def test_viewer_revocation_during_read_fails_before_returning_bytes(pg_profiles, monkeypatch):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        store, saved, manifest = published(location)
        append(location, manifest)
        original = store._read_blob
        def revoke(*args, **kwargs):
            data = original(*args, **kwargs)
            rooms.disband_room(location, room_id="room", expected_gateway_id="owner", expected_epoch=1)
            return data
        monkeypatch.setattr(store, "_read_blob", revoke)
        with pytest.raises(AttachmentNotFoundError):
            store.read_viewer(room_id="room", attachment_id=saved["attachment_id"], event_id="event", authority_gateway_id="owner", authority_epoch=1)


def test_recipient_range_and_canonical_blob_digest_are_enforced(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        store, saved, manifest = published(location)
        append(location, manifest)
        selection = dict(room_id="room", attachment_id=saved["attachment_id"], event_id="event", recipient_member_id="ops")
        assert store.describe(**selection)["sha256"] == saved["sha256"]
        assert store.read_range(**selection, offset=4, length=7).data == PNG[4:11]
        with pytest.raises(AttachmentNotFoundError):
            store.read(**(selection | {"recipient_member_id": "other"}))
        blob = next(path for path in store.blob_root.iterdir() if path.name.startswith("blob_"))
        blob.write_bytes(b"x" * len(PNG))
        with pytest.raises(AttachmentIntegrityError):
            store.read(**selection)


def test_captured_namespace_refuses_replaced_dataset_before_touching_rows_or_files(pg_profiles):
    import secrets
    from sqlalchemy import update, select, func
    from hermes_db.domains.rooms.api import open_room_store
    from hermes_db.errors import StorageConfigurationError
    from hermes_db.tables.room_attachments import roots, attachments
    with pg_profiles("one"):
        location = rooms.default_db_path()
        store, _, _ = published(location)
        blob = next(path for path in store.blob_root.iterdir() if path.name.startswith("blob_"))
        with open_room_store(location) as resource, resource.write() as conn:
            conn.execute(update(roots).where(roots.c.store_id == resource.scope.store_id).values(namespace=secrets.token_hex(16)))
        for operation in (store.stats, store.prune, store._sweep_orphans):
            with pytest.raises(StorageConfigurationError, match="dataset changed"):
                operation()
        with open_room_store(location) as resource, resource.read() as conn:
            assert conn.scalar(select(func.count()).select_from(attachments).where(attachments.c.store_id == resource.scope.store_id)) == 1
        assert blob.read_bytes() == PNG


def test_late_file_gate_does_not_recreate_removed_content_root(pg_profiles):
    import shutil
    with pg_profiles("one") as home:
        store = HostedRoomAttachmentStore(rooms.default_db_path())
        target = store.root.resolve()
        assert target.parent == (home / "hosted-room-attachments").resolve() and target.name == store.namespace
        shutil.rmtree(target)
        with pytest.raises(FileNotFoundError):
            store._sweep_orphans()
        assert not target.exists()
