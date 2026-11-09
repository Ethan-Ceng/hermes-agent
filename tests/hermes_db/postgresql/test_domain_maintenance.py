"""Interrupted file effects resume against durable PG intents without borrowing SQL for IO."""

from pathlib import Path
from contextlib import contextmanager
import os
import subprocess
import sys
import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@contextmanager
def lose_completion_ack(monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.backends.postgresql.transactions import Transactions
    from hermes_db.domains.kanban.postgres import repository as repo
    original, event, completed = Transactions.write, repo.event, []
    def observed(conn, store, task_id, kind, *args, **kwargs):
        result = event(conn, store, task_id, kind, *args, **kwargs)
        if kind == "completed":
            completed.append(conn)
        return result
    @contextmanager
    def lost(self, **kwargs):
        with original(self, **kwargs) as conn:
            yield conn
        if conn in completed:
            raise UnknownCommitError("real completion committed without confirmation")
    with monkeypatch.context() as fault:
        fault.setattr(repo, "event", observed)
        fault.setattr(Transactions, "write", lost)
        yield
    assert completed


@pytest.mark.parametrize("removed_before_crash", [False, True])
def test_maintenance_resumes_workspace_token_and_releases_reference_fence(pg_profiles, monkeypatch, removed_before_crash):
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_db.errors import StorageBusyError
    with pg_profiles("one") as home:
        with kbc.connect_closing() as store:
            task = kb.create_task(store, title="finished", workspace_kind="scratch")
            waiting = kb.create_task(store, title="new reference")
            path = kb.workspaces_root() / task
            path.mkdir(parents=True)
            workspace.set_workspace_path(store, task, path)
            with store.write() as conn:
                repo.task_update(conn, store, task, status="done")
            original = workspace.shutil.rmtree
            def interrupted(directory):
                assert store._transactions.engine.pool.checkedout() == 0
                if removed_before_crash:
                    original(directory)
                raise OSError("interrupted cleanup")
            with monkeypatch.context() as fault:
                fault.setattr(workspace.shutil, "rmtree", interrupted)
                kb._cleanup_workspace(store, task)
            with pytest.raises(StorageBusyError):
                workspace.set_workspace_path(store, waiting, path)
    from hermes_db.maintenance import maintain_profile
    with pg_profiles("two"):
        if removed_before_crash:
            root = Path(__file__).resolve().parents[3]
            child = subprocess.run([sys.executable, str(root / "tests/hermes_db/postgresql/scenarios/domain_maintenance.py"), str(home)],
                cwd=root, env={**os.environ, "PYTHONPATH": str(root)}, capture_output=True, text=True, check=False, timeout=60)
            assert child.returncode == 0, child.stderr
        else:
            maintain_profile(home)
    assert not path.exists()
    with pg_profiles("one"), kbc.connect_closing() as reopened:
        workspace.set_workspace_path(reopened, waiting, path)
        assert kb.get_task(reopened, waiting).workspace_path == str(path)
    with pg_profiles("two"), kbc.connect_closing() as other:
        assert kb.list_tasks(other) == []


def test_maintenance_replays_retirement_then_does_not_move_recreated_slug(pg_profiles, monkeypatch):
    from hermes_db.domains.kanban.postgres import files
    with pg_profiles("one") as home:
        kb.create_board("retired", name="Original")
        with monkeypatch.context() as fault:
            def interrupted(store, row):
                raise OSError("archive interrupted after SQL commit")
            fault.setattr(files, "_archive_files", interrupted)
            with pytest.raises(OSError):
                kb.remove_board("retired", archive=True)
    from hermes_db.maintenance import maintain_profile
    with pg_profiles("two"):
        maintain_profile(home)
    with pg_profiles("one"):
        kb.create_board("retired", name="Replacement")
        maintain_profile(home)
        assert kb.read_board_metadata("retired")["name"] == "Replacement"
        assert len(list((home / "kanban" / "boards" / "_archived").iterdir())) == 1


def test_pg_physical_recovery_refuses_before_copy_or_sqlite(pg_profiles, tmp_path):
    from hermes_cli.session_recovery import inspect_session_database, recover_session_database, SessionRecoverySafetyError
    source = tmp_path / "old.db"
    source.write_bytes(b"preserve historical database")
    with pg_profiles("one"):
        with pytest.raises(SessionRecoverySafetyError, match="SQLite-only"):
            inspect_session_database(source, work_dir=tmp_path / "stage")
        with pytest.raises(SessionRecoverySafetyError, match="SQLite-only"):
            recover_session_database(source, tmp_path / "output.db", work_dir=tmp_path / "stage")
    assert not (tmp_path / "stage").exists() and not (tmp_path / "output.db").exists()
    assert source.read_bytes() == b"preserve historical database"


def test_committed_completion_recovers_downstream_and_hook_after_lost_ack(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.maintenance import maintain_profile
    hooks = []
    monkeypatch.setattr(kb, "_fire_task_hook", lambda event, task, task_id, run_id, **fields: hooks.append((event, task_id)))
    with pg_profiles("one") as home, kbc.connect_closing() as board:
        parent = kb.create_task(board, title="parent")
        child = kb.create_task(board, title="child")
        kb.link_tasks(board, parent, child)
        with lose_completion_ack(monkeypatch):
            with pytest.raises(UnknownCommitError):
                kb.complete_task(board, parent, result="durably finished")
        assert kb.get_task(board, parent).status == "done"
        assert kb.get_task(board, child).status == "todo"
        assert hooks == []
    with pg_profiles("two"):
        maintain_profile(home)
        maintain_profile(home)
    with pg_profiles("one"), kbc.connect_closing() as board:
        assert kb.get_task(board, child).status == "ready"
        assert hooks == [("kanban_task_completed", parent)]


def test_deleted_task_cannot_strand_interrupted_workspace_intent(pg_profiles, monkeypatch):
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_db.maintenance import maintain_profile
    with pg_profiles("one") as home, kbc.connect_closing() as board:
        task = kb.create_task(board, title="removable", workspace_kind="scratch")
        path = kb.workspaces_root() / task
        path.mkdir(parents=True)
        workspace.set_workspace_path(board, task, path)
        with board.write() as conn:
            repo.task_update(conn, board, task, status="done")
        with monkeypatch.context() as fault:
            def interrupted(directory):
                raise OSError("interrupted before directory removal")
            fault.setattr(workspace.shutil, "rmtree", interrupted)
            kb._cleanup_workspace(board, task)
        assert kb.delete_task(board, task)
        maintain_profile(home)
        assert not path.exists()


def test_attachment_deletion_failure_retains_intent_until_fresh_process_replays(pg_profiles, monkeypatch):
    from hermes_db.errors import StorageBusyError
    from hermes_db.maintenance import maintain_profile
    with pg_profiles("one") as home, kbc.connect_closing() as board:
        task = kb.create_task(board, title="attachment owner")
        identity = kb.store_attachment_bytes(board, task, "proof.txt", b"durable content")
        path = Path(kb.get_attachment(board, identity).stored_path)
        original = Path.unlink
        with monkeypatch.context() as fault:
            def interrupted(candidate, *args, **kwargs):
                if candidate == path:
                    raise PermissionError("interrupted unlink")
                return original(candidate, *args, **kwargs)
            fault.setattr(Path, "unlink", interrupted)
            with pytest.raises(PermissionError):
                kb.delete_attachment(board, identity)
        assert path.read_bytes() == b"durable content"
        with pytest.raises(StorageBusyError):
            kb.add_attachment(board, task, filename="proof.txt", stored_path=str(path))
    with pg_profiles("two"):
        maintain_profile(home)
    assert not path.exists()


def test_unknown_uncommitted_file_generation_is_swept_but_old_dataset_marker_is_preserved(pg_profiles, monkeypatch):
    from contextlib import contextmanager
    import json
    from hermes_db.backends.postgresql.transactions import Transactions
    from hermes_db.errors import UnknownCommitError
    from hermes_db.maintenance import maintain_profile
    with pg_profiles("one") as home, kbc.connect_closing() as board:
        task = kb.create_task(board, title="uncertain upload")
        original = Transactions.write
        @contextmanager
        def uncertain(self, **kwargs):
            try:
                with original(self, **kwargs) as conn:
                    yield conn
                    raise OSError("injected rollback during disconnect")
            except OSError:
                raise UnknownCommitError("client cannot establish commit verdict") from None
        with monkeypatch.context() as fault:
            fault.setattr(Transactions, "write", uncertain)
            with pytest.raises(UnknownCommitError):
                kb.store_attachment_bytes(board, task, "uncertain.txt", b"orphan")
        assert kb.list_attachments(board, task) == []
        orphan = next(kb.task_attachments_dir(task).rglob("uncertain.txt"))
        old = orphan.parent.parent / ("f" * 32)
        old.mkdir()
        (old / "keep.txt").write_bytes(b"old dataset")
        (old / ".owner.json").write_text(json.dumps({"home": str(home), "store_id": "old", "target": "old"}), encoding="utf-8")
        maintain_profile(home)
        assert not orphan.exists()
        assert (old / "keep.txt").read_bytes() == b"old dataset"


def test_maintenance_prunes_plugin_ttl_without_reusing_revisions_and_replays_room_blob_jobs(pg_profiles, monkeypatch):
    from sqlalchemy import update
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.tables.plugins import records
    from hermes_db.maintenance import maintain_profile
    from plugins.plugin_storage import plugin_store
    from gateway.hosted_room_attachments import HostedRoomAttachmentStore, UNCOMMITTED_TTL_SECONDS
    from gateway import hosted_rooms as rooms
    from tests.gateway.test_hosted_room_attachments import PNG
    with pg_profiles("one") as home:
        plugin = plugin_store("discord", namespace="ttl-maintenance")
        first = plugin.put("key", {"old": True}, ttl_seconds=60)
        with acquire_profile_domain("plugins") as resource, resource.write() as conn:
            conn.execute(update(records).where(records.c.store_id == resource.scope.require_store_id()).values(expires_at=0))
        store = HostedRoomAttachmentStore(rooms.default_db_path(), clock=lambda: 100)
        store.put(room_id="r", upload_id="u", kind="image", name="proof.png", mime="image/png", data=PNG)
        blob = next(store.blob_root.iterdir())
        original = Path.unlink
        with monkeypatch.context() as fault:
            def interrupted(candidate, *args, **kwargs):
                if candidate == blob:
                    raise PermissionError("room unlink interrupted")
                return original(candidate, *args, **kwargs)
            fault.setattr(Path, "unlink", interrupted)
            with pytest.raises(PermissionError):
                store.prune(now=100 + UNCOMMITTED_TTL_SECONDS + 1)
        assert blob.exists()
    with pg_profiles("two"):
        other = plugin_store("discord", namespace="ttl-maintenance")
        other.put("key", {"other": True})
        maintain_profile(home)
        assert other.get("key").value == {"other": True}
    assert not blob.exists()
    with pg_profiles("one"):
        second = plugin.put("key", {"new": True}, expected_revision=0)
        assert second.revision > first.revision


def test_archived_board_cannot_poison_pending_completion_recovery(pg_profiles, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.maintenance import maintain_profile
    hooks = []
    monkeypatch.setattr(kb, "_fire_task_hook", lambda event, task, task_id, run_id, **fields: hooks.append((event, fields.get("board"))))
    with pg_profiles("one") as home:
        kb.create_board("archive")
        with kbc.connect_closing(board="archive") as store:
            task = kb.create_task(store, title="finished before archive", workspace_kind="scratch")
            path = kb.workspaces_root(board="archive") / task
            path.mkdir(parents=True)
            workspace.set_workspace_path(store, task, path)
            with lose_completion_ack(monkeypatch):
                with pytest.raises(UnknownCommitError):
                    kb.complete_task(store, task, result="finished")
        kb.remove_board("archive", archive=True)
        maintain_profile(home)
        assert not path.exists()
        assert hooks == [("kanban_task_completed", "archive")]
