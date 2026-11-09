"""Canonical upload/Send/download and the member input bridge operate on real PG."""

import base64
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway import hosted_room_driver as driver
from gateway.session_hosted_service import CanonicalHostedRoomService
from gateway.session_hosted_attachments import upload, download, submission_payload
from hermes_db.access import open_session_store
from hermes_db.integration.runtime_access import runtime_for_store

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_real_canonical_plain_and_file_send_persist_tasks_and_materialize_member_bytes(pg_profiles):
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        authority = SimpleNamespace(db=db, profile_id=str(home), epoch=runtime_for_store(db).begin_epoch(instance_id="owner"))
        service = CanonicalHostedRoomService(authority, None)
        service.local_profiles = lambda: ("ops", "review")
        for room_id in ("plain", "room"):
            service.create_room(room_id=room_id, name=room_id, members=[dict(member_id=name, profile=name, handle=name) for name in service.local_profiles()],
                admit=service._coordination.owner_effect("alice", room_id))
        assert service.send(room_id="plain", event_id="plain-message", payload=dict(text="hello", thread_id="plain-thread"))["kind"] == "message.user"
        assert len(driver.list_tasks(service.db_path, room_id="plain", status="queued")) == 1
        actor = SimpleNamespace(subject="alice", profile_id=str(home), capabilities={"session:read", "session:submit"})
        data = "实际附件 bytes🙂\n".encode()
        metadata = upload(service, actor, dict(room_id="room", upload_id="upload", kind="file", name="note.txt", mime="text/plain",
            data_base64=base64.b64encode(data).decode()))
        manifest = [{key: metadata[key] for key in ("attachment_id", "kind", "name", "size", "mime")}]
        event = service.send(room_id="room", event_id="file-message", payload=dict(text="@ops read this", thread_id="thread", attachments=manifest))
        assert event["payload"]["attachments"] == manifest
        task = driver.list_tasks(service.db_path, room_id="room", status="queued")[0]
        assert task["payload"]["attachments"] == [dict(manifest[0], event_id="file-message")]
        rpc = SimpleNamespace(room_db_path=service.db_path, room_id="room", member_id="ops")
        payload = submission_payload(rpc, task["payload"]["prompt"], task["payload"]["attachments"])
        materialized = Path(payload["text"].split("file: ")[-1].split("\n")[0])
        assert materialized.read_bytes() == data
        received = download(service, actor, dict(room_id="room", event_id="file-message", attachment_id=metadata["attachment_id"]))
        assert base64.b64decode(received["data_base64"]) == data
        restarted = CanonicalHostedRoomService(authority, None)
        restarted.local_profiles = lambda: ("ops", "review")
        assert sorted(binding.room_id for binding in restarted.bindings()) == ["plain", "room"]
        assert driver.get_task(restarted.db_path, task["identity"])["payload"] == task["payload"]
