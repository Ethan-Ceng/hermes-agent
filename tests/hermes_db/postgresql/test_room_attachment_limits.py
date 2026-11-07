"""Logical/physical quotas, uncommitted caps and cross-store cleanup on PG."""

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore, AttachmentQuotaError, MAX_ROOM_UNCOMMITTED_COUNT
from tests.gateway.test_hosted_room_attachments import PNG, _manifest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def put(store, room_id="room", upload_id="upload", data=PNG):
    return store.put(room_id=room_id, upload_id=upload_id, kind="image", name="image.png", mime="image/png", data=data)


def test_room_logical_gateway_physical_and_total_count_limits_are_independent(pg_profiles):
    with pg_profiles("one"):
        location = rooms.default_db_path()
        store = HostedRoomAttachmentStore(location, room_quota_bytes=len(PNG), gateway_quota_bytes=len(PNG), gateway_quota_count=2)
        put(store, "first")
        put(store, "second")
        assert store.stats()["logical_bytes"] == 2 * len(PNG) and store.stats()["physical_bytes"] == len(PNG)
        with pytest.raises(AttachmentQuotaError, match="room attachment quota"):
            put(store, "first", "extra")
        with pytest.raises(AttachmentQuotaError, match="gateway attachment count"):
            put(store, "third")
        physical = HostedRoomAttachmentStore(location, room_quota_bytes=2 * len(PNG), gateway_quota_bytes=len(PNG))
        with pytest.raises(AttachmentQuotaError, match="gateway attachment quota"):
            put(physical, "third", data=PNG + b"different")
        physical.prune()
        assert physical.stats()["attachments"] == 2 and len(tuple(physical.blob_root.iterdir())) == 1


def test_uncommitted_count_cap_rejects_metadata_and_reclaims_candidate(pg_profiles):
    with pg_profiles("one"):
        store = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100)
        for index in range(MAX_ROOM_UNCOMMITTED_COUNT):
            put(store, upload_id=f"upload-{index}")
        with pytest.raises(AttachmentQuotaError, match="uncommitted"):
            put(store, upload_id="overflow")
        assert store.stats()["attachments"] == MAX_ROOM_UNCOMMITTED_COUNT
        store.prune()
        assert len(tuple(store.blob_root.iterdir())) == 1


def test_pruning_one_store_cannot_release_another_stores_identical_hash(pg_profiles):
    with pg_profiles("one"):
        first = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100)
        put(first)
    with pg_profiles("two"):
        second = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100)
        saved = put(second)
        assert second.namespace != first.namespace
        second.commit_message(room_id="room", event_id="event", manifest=_manifest(saved), recipient_member_ids=["ops"])
        first.mark_room_disbanded("room")
        assert first.prune(now=2000) == 1 and first.stats()["blobs"] == 0
        assert second.stats()["attachments"] == 1 and second.stats()["blobs"] == 1
        assert second.read(room_id="room", event_id="event", attachment_id=saved["attachment_id"], recipient_member_id="ops").data == PNG
