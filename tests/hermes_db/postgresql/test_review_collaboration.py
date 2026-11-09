"""Independent review reproductions; disposable Profiles and owned schema only."""
from pathlib import Path
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_imported_board_can_be_retired(pg_profiles, tmp_path):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_transfer as transfer
    with pg_profiles("review-source"):
        kb.create_board("source")
        with kbc.connect_closing(board="source") as board:
            kb.create_task(board, title="export source")
        archive = transfer.export_board("source", str(tmp_path / "archive"))["archive"]
    with pg_profiles("review-target"):
        transfer.import_board(archive, "imported")
        result = kb.remove_board("imported", archive=True)
        assert result["action"] == "archived"


def test_completed_archive_can_be_deleted(pg_profiles):
    from hermes_cli import kanban_db as kb
    with pg_profiles("review-archive"):
        kb.create_board("archived")
        kb.remove_board("archived", archive=True)
        result = kb.remove_board("archived", archive=False)
        assert result["action"] == "deleted"


def test_alias_attachment_retains_shared_file(pg_profiles):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    with pg_profiles("review-alias") as home:
        with kbc.connect_closing() as board:
            task = kb.create_task(board, title="shared file")
            parent = home / "files"
            parent.mkdir()
            (parent / "subdir").mkdir()
            path = parent / "proof.txt"
            path.write_bytes(b"still referenced")
            first = kb.add_attachment(board, task, filename="first", stored_path=str(path), size=16)
            alias = str(parent / "subdir" / ".." / "proof.txt")
            second = kb.add_attachment(board, task, filename="second", stored_path=alias, size=16)
            assert kb.get_attachment(board, second) is not None
            kb.delete_attachment(board, first)
            assert Path(kb.get_attachment(board, second).stored_path).read_bytes() == b"still referenced"


def test_unknown_rejected_claim_replays_original_verdict(pg_profiles, monkeypatch):
    from uuid import uuid4
    from sqlalchemy.exc import OperationalError
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_db.domains.kanban.api import BoardResource
    from hermes_db.domains.kanban.postgres.receipts import CommandReceipt, CommandReplay
    from hermes_db.errors import UnknownCommitError
    with pg_profiles("review-rejected-claim"), kbc.connect_closing() as board:
        parent = kb.create_task(board, title="unfinished parent")
        child = kb.create_task(board, title="child", parents=[parent])
        engine = board._transactions.engine
        commit = engine.dialect.do_commit
        command_id = uuid4().hex

        def lose_ack(connection):
            commit(connection)
            raise OperationalError("review: acknowledgement lost", None, None)

        with BoardResource(board, board.board_id, board.slug, command=CommandReceipt(command_id, "frozen")) as command:
            with monkeypatch.context() as patch:
                patch.setattr(engine.dialect, "do_commit", lose_ack)
                with pytest.raises(UnknownCommitError):
                    kb.claim_task(command, child)
        assert kb.get_task(board, child).status == "todo"
        kb.complete_task(board, parent, summary="parent has finished")
        assert kb.get_task(board, child).status == "ready"
        with BoardResource(board, board.board_id, board.slug, command=CommandReceipt(command_id, "frozen")) as retry:
            with pytest.raises(CommandReplay) as replay:
                kb.claim_task(retry, child)
            assert replay.value.result is None


@pytest.mark.parametrize("method,params", [("groups.list", {}), ("groups.state", {"room_id": "room"})])
def test_desktop_group_forward_accepts_pg_location(pg_profiles, monkeypatch, method, params):
    from types import SimpleNamespace
    from tui_gateway import methods_groups_forward as forwarding
    server = SimpleNamespace(_current_profile_name=lambda: "", _ok=lambda rid, result: {"result": result},
                             _err=lambda rid, code, message, *data: {"error": {"code": code, "message": message}})
    monkeypatch.setattr(forwarding, "owner_endpoint", lambda home: object())
    monkeypatch.setattr(forwarding, "_call", lambda *args: {"result": {"rooms": [], "native_owner": True}})
    with pg_profiles("review-forward"):
        result = forwarding.forward(server, 1, method, params)
        assert result["result"]["native_owner"]


@pytest.mark.asyncio
async def test_canonical_group_entry_accepts_pg_location(pg_profiles):
    from contextlib import closing
    from types import SimpleNamespace
    from gateway.session_group_controls import dispatch_group_control
    from hermes_db.access import open_session_store
    with pg_profiles("review-native-groups") as home, closing(open_session_store(home / "state.db")) as db:
        actor = SimpleNamespace(profile_id=str(home), subject="review", capabilities={"session:read"})
        authority = SimpleNamespace(db=db, profile_id=str(home), runner=object())
        connection = SimpleNamespace(authority=authority, actor=actor, host_scoped=False)
        result = await dispatch_group_control(connection, "groups.list", {})
        assert result["rooms"] == []
