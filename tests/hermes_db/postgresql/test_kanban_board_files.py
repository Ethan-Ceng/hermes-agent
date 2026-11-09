"""PG Board file roots retain the same immutable generation identity as their rows."""

from pathlib import Path
import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_recreated_slug_never_reuses_retired_board_content_root(pg_profiles, monkeypatch):
    monkeypatch.setattr(kb, "_new_task_id", lambda: "same-task")
    with pg_profiles("one"):
        kb.create_board("named")
        with kbc.connect_closing(board="named") as first:
            task = kb.create_task(first, title="old content")
            attachment = kb.store_attachment_bytes(first, task, "proof.txt", b"old generation")
            stored = Path(kb.get_attachment(first, attachment).stored_path)
            first_root = kb.attachments_root(board="named")
            kb.remove_board("named", archive=True)
            kb.create_board("named")
            with kbc.connect_closing(board="named") as second:
                assert kb.attachments_root(board="named") != first_root
                assert kb.create_task(second, title="new content") == task
                assert kb.list_attachments(second, task) == []
                assert stored.read_bytes() == b"old generation"
                assert kb.get_attachment(first, attachment).stored_path == str(stored)


@pytest.mark.parametrize("failure", ["after_commit", "file_io"])
def test_archive_intent_recovers_interruption_before_allowing_slug_reuse(pg_profiles, monkeypatch, failure):
    from contextlib import contextmanager
    from hermes_db.errors import StorageBusyError, UnknownCommitError
    from hermes_db.domains.kanban.postgres.operations import file_jobs as files
    with pg_profiles("one"):
        kb.create_board("interrupted", name="Kept name")
        with kbc.connect_closing(board="interrupted") as store:
            task = kb.create_task(store, title="durable")
            attachment = kb.store_attachment_bytes(store, task, "proof.txt", b"proof")
            stored = Path(kb.get_attachment(store, attachment).stored_path)
            with monkeypatch.context() as fault:
                if failure == "after_commit":
                    transactions_type = type(store._transactions)
                    original = transactions_type.write

                    @contextmanager
                    def lost_ack(transactions, **kwargs):
                        with original(transactions, **kwargs) as conn:
                            yield conn
                        raise UnknownCommitError("test retirement acknowledgement lost")

                    fault.setattr(transactions_type, "write", lost_ack)
                    expected = UnknownCommitError
                else:
                    def failed_files(row):
                        raise OSError("test archive interrupted")
                    fault.setattr(files, "_archive_files", failed_files)
                    expected = OSError
                with pytest.raises(expected):
                    kb.remove_board("interrupted", archive=True)
            assert kb.read_board_metadata("interrupted")["archived"]
            with pytest.raises(StorageBusyError, match="pending"):
                kb.create_board("interrupted")
            result = kb.remove_board("interrupted", archive=True)
            archive = Path(result["new_path"])
            assert (archive / "contents.json").is_file() and (archive / "board.json").is_file()
            assert not result["files_pending"] and stored.read_bytes() == b"proof"
            kb.create_board("interrupted", name="New generation")
            assert kb.read_board_metadata("interrupted")["name"] == "New generation"


def test_hard_delete_preserves_shared_content_and_fences_new_references(pg_profiles, monkeypatch):
    from hermes_cli import kanban_db_workspace as workspace
    from hermes_db.errors import StorageBusyError
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.domains.kanban.postgres.operations import file_jobs as files, file_cleanup as cleanup
    with pg_profiles("one"):
        kb.create_board("victim")
        kb.create_board("survivor")
        with kbc.connect_closing(board="victim") as victim, kbc.connect_closing(board="survivor") as survivor:
            task = kb.create_task(victim, title="victim")
            directory = kb.workspaces_root(board="victim") / task
            directory.mkdir(parents=True)
            workspace.set_workspace_path(victim, task, directory)
            attachment = kb.store_attachment_bytes(victim, task, "shared.txt", b"shared")
            stored = Path(kb.get_attachment(victim, attachment).stored_path)
            other = kb.create_task(survivor, title="still uses files", workspace_kind="dir", workspace_path=str(directory))
            reference = kb.add_attachment(survivor, other, filename="shared.txt", stored_path=str(stored), size=6)
            deleted = kb.remove_board("victim", archive=False)
            assert deleted["files_pending"] and stored.read_bytes() == b"shared" and directory.is_dir()
            kb.create_board("victim", name="New generation")
            new_config = kb.board_dir("victim") / "board.json"
            assert kb.delete_attachment(survivor, reference) is not None
            assert kb.delete_task(survivor, other)
            fresh = kb.create_task(survivor, title="must not reference retirement")
            original = cleanup.shutil.rmtree
            fenced = []

            def remove(path):
                assert victim._transactions.engine.pool.checkedout() == 0
                with pytest.raises(StorageBusyError, match="retired"):
                    workspace.set_workspace_path(survivor, fresh, directory)
                with pytest.raises(StorageBusyError, match="retired"):
                    kb.add_attachment(survivor, fresh, filename="late.txt", stored_path=str(stored))
                fenced.append(True)
                original(path)

            monkeypatch.setattr(cleanup.shutil, "rmtree", remove)
            with acquire_profile_domain("kanban_tasks") as resource:
                assert not files.run_job(resource, victim.board_id)["files_pending"]
                assert not files.run_job(resource, victim.board_id)["files_pending"]
            assert fenced == [True]
            assert not directory.exists() and new_config.is_file()
            assert kb.get_task(survivor, fresh).workspace_path is None
