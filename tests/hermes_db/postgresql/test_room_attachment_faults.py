"""Real file/metadata failure windows, process restart and scope-safe cleanup."""

from pathlib import Path
import subprocess
import sys

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore, UNCOMMITTED_TTL_SECONDS
from tests.gateway.test_hosted_room_attachments import PNG

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def put(store, upload_id="upload"):
    return store.put(room_id="room", upload_id=upload_id, kind="image", name="image.png", mime="image/png", data=PNG)


def child(home, role):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    script = Path(__file__).with_name("scenarios") / "room_attachments.py"
    env = child_env()
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
    return subprocess.run([sys.executable, str(script), role], cwd=Path(__file__).resolve().parents[3], env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def test_file_success_database_refusal_leaves_recoverable_orphan_and_no_row(pg_profiles, monkeypatch):
    from hermes_db.errors import StorageWriteError
    from hermes_db.domains.rooms.attachments.postgres.operations import uploads as room_attachment_uploads
    with pg_profiles("one"):
        store = HostedRoomAttachmentStore(rooms.default_db_path())
        def refuse(*args, **kwargs):
            raise StorageWriteError("injected attachment SQL refusal")
        with monkeypatch.context() as patch:
            patch.setattr(room_attachment_uploads, "put", refuse)
            with pytest.raises(StorageWriteError):
                put(store)
        assert store.stats() == dict(attachments=0, logical_bytes=0, blobs=0, physical_bytes=0)
        assert len(tuple(store.blob_root.iterdir())) == 1
        store._sweep_orphans()
        assert not tuple(store.blob_root.iterdir())
        assert put(store)["state"] == "uploaded"


def test_actual_metadata_commit_lost_ack_keeps_unique_bytes_and_restarts(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.domains.rooms.attachments.postgres.operations import uploads as room_attachment_uploads
    with pg_profiles("one") as home:
        location = rooms.default_db_path()
        store = HostedRoomAttachmentStore(location)
        original = room_attachment_uploads.put
        def lose_ack(*args, **kwargs):
            original(*args, **kwargs)  # The real PG business transaction commits first.
            raise UnknownCommitError("injected attachment commit confirmation loss")
        with monkeypatch.context() as patch:
            patch.setattr(room_attachment_uploads, "put", lose_ack)
            with pytest.raises(UnknownCommitError):
                put(store)
        assert store.stats()["attachments"] == 1 and len(tuple(store.blob_root.iterdir())) == 1
        assert put(store)["idempotent"]
        result = child(home, "read")
        assert result.returncode == 0, result.stderr
        assert "PG_ATTACHMENT_RESTART_READ_OK" in result.stdout
        assert HostedRoomAttachmentStore(location).stats()["physical_bytes"] == len(PNG)


def test_cleanup_failure_is_persistent_and_new_process_replays_exact_blob_job(pg_profiles, monkeypatch):
    from hermes_db.domains.rooms.api import open_room_store
    from hermes_db.domains.rooms.attachments.postgres.operations.cleanup import pending_jobs
    with pg_profiles("one") as home:
        now = [100.0]
        store = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: now[0])
        put(store)
        blob = next(iter(store.blob_root.iterdir()))
        now[0] += UNCOMMITTED_TTL_SECONDS + 1
        original = type(blob).unlink
        def refuse(path, *args, **kwargs):
            if path == blob:
                raise PermissionError("injected private blob deletion refusal")
            return original(path, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(type(blob), "unlink", refuse)
            with pytest.raises(PermissionError):
                store.prune()
        assert blob.read_bytes() == PNG and store.stats()["attachments"] == 0
        with open_room_store(store.db_path) as resource:
            assert pending_jobs(resource, store.namespace) == [blob.name]
        result = child(home, "cleanup")
        assert result.returncode == 0, result.stderr
        assert "PG_ATTACHMENT_RESTART_CLEANUP_OK" in result.stdout and not blob.exists()
        with open_room_store(store.db_path) as resource:
            assert pending_jobs(resource, store.namespace) == []


def test_content_io_never_holds_a_pg_connection(pg_profiles, monkeypatch):
    from hermes_db.domains.rooms.api import open_room_store
    from hermes_db.backends.postgresql.engine import get_engine
    with pg_profiles("one"):
        store = HostedRoomAttachmentStore(rooms.default_db_path())
        with open_room_store(store.db_path) as resource:
            engine = get_engine(resource.settings.postgresql)
        original_write, original_read = store._write_blob, store._read_blob
        witnessed = []
        def write(*args, **kwargs):
            borrowed = engine.pool.checkedout()
            assert borrowed == 0
            witnessed.append("write")
            return original_write(*args, **kwargs)
        def read(*args, **kwargs):
            borrowed = engine.pool.checkedout()
            assert borrowed == 0
            witnessed.append("read")
            return original_read(*args, **kwargs)
        monkeypatch.setattr(store, "_write_blob", write)
        monkeypatch.setattr(store, "_read_blob", read)
        saved = put(store)
        manifest = [{key: saved[key] for key in ("attachment_id", "kind", "name", "size", "mime")}]
        store.commit_message(room_id="room", event_id="event", manifest=manifest, recipient_member_ids=["ops"])
        assert store.read(room_id="room", attachment_id=saved["attachment_id"], recipient_member_id="ops", event_id="event").data == PNG
        assert witnessed == ["write", "read", "read"]
