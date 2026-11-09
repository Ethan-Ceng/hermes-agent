"""Independent process quotas and a real server transaction resolving before file sweep."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Event, current_thread

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_attachments import HostedRoomAttachmentStore
from tests.gateway.test_hosted_room_attachments import PNG

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_two_actual_processes_respect_shared_room_quota_and_keep_one_blob(pg_profiles):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        store = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100, room_quota_count=1)
        script = Path(__file__).with_name("scenarios") / "room_attachments.py"
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
        children = [subprocess.Popen([sys.executable, str(script), role], cwd=Path(__file__).resolve().parents[3], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for role in ("quota-a", "quota-b")]
        try:
            for child in children:
                child.stdin.write("go\n")
                child.stdin.flush()
            results = [child.communicate(timeout=60) for child in children]
            assert all(child.returncode == 0 for child in children), [stderr for _, stderr in results]
            assert sorted(stdout.strip() for stdout, _ in results) == ["QUOTA_ACCEPTED", "QUOTA_REFUSED"]
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
        assert store.stats()["attachments"] == 1 and store.stats()["physical_bytes"] == len(PNG)
        store.prune()
        files = tuple(store.blob_root.iterdir())
        assert len(files) == 1 and files[0].read_bytes() == PNG


def test_sweep_waits_for_real_pending_sql_commit_before_deciding_file_liveness(pg_profiles, monkeypatch):
    from sqlalchemy import text, select, func
    from hermes_db.domains.rooms.api import open_room_store
    from hermes_db.backends.postgresql.transactions import Transactions
    from hermes_db.domains.rooms.postgres import repository as repo
    from hermes_db.tables.room_attachments import attachments, blobs
    from tests.waiting import wait_until
    with pg_profiles("one"):
        store = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100)
        blob_id, attachment_id = "blob_" + secrets.token_hex(16), "att_" + secrets.token_hex(16)
        target = store._blob_path(blob_id)
        store._write_blob(target, PNG)
        inserted, sweep_connected, blocked, release = Event(), Event(), Event(), Event()
        pids = {}
        original_write = Transactions.write
        @contextmanager
        def observe(self, *args, **kwargs):
            with original_write(self, *args, **kwargs) as conn:
                if current_thread().name.startswith("attachment-sweep"):
                    pids["sweep"] = conn.scalar(select(func.pg_backend_pid()))
                    sweep_connected.set()
                yield conn
        monkeypatch.setattr(Transactions, "write", observe)
        def server_commit():
            with open_room_store(store.db_path) as resource, resource.write() as conn:
                repo.lock_store(conn, resource)
                pids["writer"] = conn.scalar(select(func.pg_backend_pid()))
                digest = hashlib.sha256(PNG).hexdigest()
                repo.insert_row(conn, resource, blobs, dict(blob_id=blob_id, sha256=digest, size=len(PNG), ref_count=1, created_at=100))
                repo.insert_row(conn, resource, attachments, dict(attachment_id=attachment_id, upload_id="pending", room_id="room", event_id=None,
                    kind="image", name="image.png", catalog_name="image.png", size=len(PNG), mime="image/png", sha256=digest, blob_id=blob_id,
                    recipient_member_ids_json="[]", viewer_access=0, state="uploaded", created_at=100, updated_at=100, expires_at=3700))
                inserted.set()
                assert sweep_connected.wait(15)
                wait_until(lambda: conn.scalar(text("SELECT :writer = ANY(pg_blocking_pids(:sweep))"), pids), what="sweep waits for unresolved PG transaction")
                blocked.set()
                assert release.wait(20)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="attachment-commit") as writers, ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="attachment-sweep") as sweepers:
            writer = writers.submit(server_commit)
            try:
                assert inserted.wait(15)
                swept = sweepers.submit(store._sweep_orphans)
                assert blocked.wait(15)
            finally:
                release.set()
            writer.result(30)
            swept.result(30)
        assert target.read_bytes() == PNG
        assert store.find_upload(room_id="room", upload_id="pending")["attachment_id"] == attachment_id
