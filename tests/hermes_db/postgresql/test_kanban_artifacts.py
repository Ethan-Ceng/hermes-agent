"""Terminal-flow prerequisite: PG metadata and durable file contents."""

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_file_contents_and_metadata_survive_reopen_and_board_scope(pg_profiles):
    with pg_profiles("one") as home:
        kb.create_board("alpha")
        kb.create_board("beta")
        with kbc.connect_closing(board="alpha") as store:
            task_id = kb.create_task(store, title="artifact", workspace_kind="scratch")
            attachment_id = kb.store_attachment_bytes(store, task_id, "report.bin", b"exact\x00\xff", uploaded_by="author")
            attachment = kb.get_attachment(store, attachment_id)
            assert attachment.task_id == task_id
            assert attachment.uploaded_by == "author" and attachment.size == 7
            path = Path(attachment.stored_path)
            assert path.is_relative_to(home)
            assert path.read_bytes() == b"exact\x00\xff"
        with kbc.connect_closing(board="beta") as other:
            assert kb.get_attachment(other, attachment_id) is None
        with kbc.connect_closing(board="alpha") as store:
            assert kb.list_attachments(store, task_id)[0].id == attachment_id
            assert kb.delete_attachment(store, attachment_id).filename == "report.bin"
            assert not path.exists()
            assert kb.list_attachments(store, task_id) == []


def test_shared_blob_reference_is_retained_until_last_board_reference(pg_profiles):
    with pg_profiles("one"):
        kb.create_board("alpha")
        kb.create_board("beta")
        with kbc.connect_closing(board="alpha") as first:
            task_id = kb.create_task(first, title="first", workspace_kind="scratch")
            aid = kb.store_attachment_bytes(first, task_id, "report.txt", b"shared")
            path = Path(kb.get_attachment(first, aid).stored_path)
        with kbc.connect_closing(board="beta") as second:
            task_id = kb.create_task(second, title="second", workspace_kind="scratch")
            bid = kb.add_attachment(second, task_id, filename=path.name, stored_path=str(path), size=6)
        with kbc.connect_closing(board="alpha") as first:
            kb.delete_attachment(first, aid)
            assert path.read_bytes() == b"shared"
        with kbc.connect_closing(board="beta") as second:
            kb.delete_attachment(second, bid)
            assert not path.exists()


def test_unknown_upload_commit_preserves_durable_file(pg_profiles, monkeypatch):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from hermes_db.errors import UnknownCommitError
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="unknown upload", workspace_kind="scratch")
        dialect = store._transactions.engine.dialect
        commit = dialect.do_commit
        def lose_ack(connection):
            commit(connection)
            raise OperationalError(None, None, psycopg.OperationalError("commit acknowledgement lost"))
        with monkeypatch.context() as failure:
            failure.setattr(dialect, "do_commit", lose_ack)
            with pytest.raises(UnknownCommitError):
                kb.store_attachment_bytes(store, task_id, "durable.bin", b"committed\x00")
        attachment = kb.list_attachments(store, task_id)[0]
        assert Path(attachment.stored_path).read_bytes() == b"committed\x00"
        assert kb.get_task(store, task_id).status == "ready"


def test_pending_cleanup_fences_new_references_without_holding_connection(pg_profiles, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Event
    from hermes_db.errors import StorageBusyError
    with pg_profiles("one"):
        kb.create_board("alpha")
        kb.create_board("beta")
        with kbc.connect_closing(board="alpha") as first, kbc.connect_closing(board="beta") as second:
            parent = kb.create_task(first, title="first", workspace_kind="scratch")
            other = kb.create_task(second, title="second", workspace_kind="scratch")
            aid = kb.store_attachment_bytes(first, parent, "pending.bin", b"shared")
            path = Path(kb.get_attachment(first, aid).stored_path)
            deleting, release = Event(), Event()
            unlink = Path.unlink
            def wait_unlink(target, *args, **kwargs):
                if target == path:
                    deleting.set()
                    assert release.wait(10)
                return unlink(target, *args, **kwargs)
            monkeypatch.setattr(Path, "unlink", wait_unlink)
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(copy_context().run, kb.delete_attachment, first, aid)
                try:
                    assert deleting.wait(10)
                    assert first._transactions.engine.pool.checkedout() == 0
                    with pytest.raises(StorageBusyError, match="cleanup is pending"):
                        kb.add_attachment(second, other, filename=path.name, stored_path=str(path))
                    assert kb.list_attachments(second, other) == []
                finally:
                    release.set()
                assert future.result().id == aid
            assert not path.exists()
