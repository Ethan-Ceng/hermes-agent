"""Second independent review, random PG namespaces and temporary Profiles only."""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_request_changes_rejected_commit_records_original_verdict(pg_profiles, monkeypatch):
    from uuid import uuid4
    from sqlalchemy.exc import OperationalError
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_db.domains.kanban.api import BoardResource
    from hermes_db.domains.kanban.postgres.receipts import CommandReceipt, CommandReplay
    from hermes_db.errors import UnknownCommitError
    with pg_profiles("review-rejected-changes"), kbc.connect_closing() as board:
        task = kb.create_task(board, title="review", assignee="coder")
        engine, command_id = board._transactions.engine, uuid4().hex
        original_commit = engine.dialect.do_commit

        def lose_ack(connection):
            original_commit(connection)
            raise OperationalError("review acknowledgement lost", None, None)

        with BoardResource(board, board.board_id, board.slug, command=CommandReceipt(command_id, "unchanged")) as first:
            with monkeypatch.context() as patch:
                patch.setattr(engine.dialect, "do_commit", lose_ack)
                with pytest.raises(UnknownCommitError):
                    kb.request_changes(first, task, reason="needs rework")
        assert kb.request_review(board, task, summary="ready for review", reviewer="reviewer")
        assert kb.claim_review_task(board, task)
        with BoardResource(board, board.board_id, board.slug, command=CommandReceipt(command_id, "unchanged")) as retry:
            with pytest.raises(CommandReplay) as replay:
                kb.request_changes(retry, task, reason="needs rework")
            assert replay.value.result == (False, "task is not in an active review run")


def test_pg_foreign_standalone_group_list_does_not_read_launch_store(pg_profiles, monkeypatch):
    from types import SimpleNamespace
    from gateway import hosted_rooms as rooms
    from tui_gateway import methods_groups, methods_groups_forward as forwarding
    members = [{"member_id": "member", "profile": "default", "handle": "member"}]
    with pg_profiles("foreign") as foreign:
        rooms.create_room(rooms.default_db_path(), room_id="same", name="foreign room", members=members,
                          authority_gateway_id="gateway")
    with pg_profiles("launch"):
        rooms.create_room(rooms.default_db_path(), room_id="same", name="launch room", members=members,
                          authority_gateway_id="gateway")
        methods = {}
        server = SimpleNamespace(_current_profile_name=lambda: "launch", _profile_home=lambda name: foreign,
                                 _ok=lambda rid, result: {"result": result},
                                 _err=lambda rid, code, message, *data: {"error": {"code": code}},
                                 register_method=lambda name, handler: methods.__setitem__(name, handler))
        monkeypatch.setattr(methods_groups, "_bound_server", server)
        monkeypatch.setattr(forwarding, "owner_endpoint", lambda home: None)
        methods_groups.register(server)
        result = methods["groups.list"](1, {"profile": "foreign"})
        assert [room["name"] for room in result["result"]["rooms"]] == ["foreign room"]


def test_phantom_completion_warning_does_not_stall_outbox(pg_profiles):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    with pg_profiles("review-phantom-outbox"), kbc.connect_closing() as board:
        parent = kb.create_task(board, title="parent")
        child = kb.create_task(board, title="child", parents=[parent])
        assert kb.get_task(board, child).status == "todo"
        assert kb.complete_task(board, parent, summary="delivered t_deadbeef")
        assert kb.get_task(board, parent).status == "done"
        assert kb.get_task(board, child).status == "ready"
        assert len([event for event in kb.list_events(board, parent) if event.kind == "suspected_hallucinated_references"]) == 1


def test_old_raw_alias_attachment_rows_retain_file_until_last_reference(pg_profiles):
    from pathlib import Path
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_db.tables.kanban_artifacts import attachments, blobs
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_db.core.values import encode_text
    with pg_profiles("review-old-alias"), kbc.connect_closing() as board:
        task = kb.create_task(board, title="old aliases")
        first = kb.store_attachment_bytes(board, task, "proof.bin", b"keep")
        path = Path(kb.get_attachment(board, first).stored_path)
        alias = str(path.parent / ".." / path.parent.name / path.name)
        second = kb.add_attachment(board, task, filename="second", stored_path=str(path), size=4)
        # Reconstruct data persisted by the preceding PG implementation, not a new write API.
        with board.write() as conn:
            conn.execute(attachments.update().where(repo.scope(attachments, board), attachments.c.id == second).values(stored_path=encode_text(alias)))
            conn.execute(blobs.insert().values(store_id=board.scope.require_store_id(), path=encode_text(alias)))
        kb.delete_attachment(board, first)
        assert Path(kb.get_attachment(board, second).stored_path).read_bytes() == b"keep"
        kb.delete_attachment(board, second)
        assert not path.exists()


@pytest.mark.parametrize("has_live_reference", [False, True])
def test_old_raw_cleanup_token_reconciles_or_preserves_canonical_live_reference(pg_profiles, has_live_reference):
    from pathlib import Path
    from sqlalchemy import select
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_db.tables.kanban_artifacts import attachments, blobs
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_db.domains.kanban.postgres.files import reconcile
    from hermes_db.integration.kanban_owner import board_files
    from hermes_db.errors import StorageBusyError
    from hermes_db.core.values import encode_text
    with pg_profiles("review-old-token"), kbc.connect_closing() as board:
        task = kb.create_task(board, title="old pending token")
        item = kb.store_attachment_bytes(board, task, "proof.bin", b"keep")
        path = Path(kb.get_attachment(board, item).stored_path)
        alias = str(path.parent / ".." / path.parent.name / path.name)
        with board.write() as conn:
            if not has_live_reference:
                conn.execute(attachments.delete().where(repo.scope(attachments, board), attachments.c.id == item))
            conn.execute(blobs.insert().values(store_id=board.scope.require_store_id(), path=encode_text(alias), cleanup_token="old-intent"))
        if has_live_reference:
            with pytest.raises(StorageBusyError):
                kb.add_attachment(board, task, filename="new", stored_path=str(path))
            with pytest.raises(StorageBusyError), board_files(board):
                reconcile(board)
            assert path.read_bytes() == b"keep"
        else:
            with board_files(board):
                reconcile(board)
            assert not path.exists()
            with board.read() as conn:
                assert conn.scalar(select(blobs.c.cleanup_token).where(blobs.c.store_id == board.scope.require_store_id(),
                    blobs.c.path == encode_text(alias))) is None


def test_actual_server_registered_groups_handlers_use_bound_module_helpers(pg_profiles, monkeypatch):
    from tui_gateway import methods_groups_forward as forwarding
    with pg_profiles("review-real-server"):
        from tui_gateway import server
        monkeypatch.setattr(forwarding, "owner_endpoint", lambda home: None)
        result = server._methods["groups.list"](1, {})
        assert result["result"]["rooms"] == []
        capabilities = server._methods["groups.capabilities"](2, {})
        assert capabilities["result"]["protocol_version"]


def test_phantom_warning_lost_commit_ack_replays_once_and_drains_following_phases(pg_profiles, monkeypatch):
    from sqlalchemy import select, func
    from sqlalchemy.exc import OperationalError
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_db.errors import UnknownCommitError
    from hermes_db.domains.kanban.postgres import completion as kanban_completion, effects as kanban_effects
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_db.tables.kanban_effects import effects
    with pg_profiles("review-phantom-replay"), kbc.connect_closing() as board:
        parent = kb.create_task(board, title="parent")
        child = kb.create_task(board, title="child", parents=[parent])
        with monkeypatch.context() as patch:
            patch.setattr(kanban_completion, "after_commit", lambda *args: None)
            assert kb.complete_task(board, parent, summary="delivered t_deadbeef")
        engine, trigger = board._transactions.engine, [False]
        commit, event = engine.dialect.do_commit, repo.event

        def observed_event(conn, store, task_id, kind, *args, **kwargs):
            result = event(conn, store, task_id, kind, *args, **kwargs)
            trigger[0] |= kind == "suspected_hallucinated_references"
            return result

        def lose_warning_ack(connection):
            commit(connection)
            if trigger[0]:
                trigger[0] = False
                raise OperationalError("review warning commit acknowledgement lost", None, None)

        with monkeypatch.context() as patch:
            patch.setattr(repo, "event", observed_event)
            patch.setattr(engine.dialect, "do_commit", lose_warning_ack)
            with pytest.raises(UnknownCommitError):
                kanban_effects.drain(board)
        with board.write() as conn:
            conn.execute(effects.update().where(effects.c.store_id == board.scope.require_store_id()).values(expires_at=0))
        kanban_effects.drain(board)
        assert kb.get_task(board, child).status == "ready"
        assert len([row for row in kb.list_events(board, parent) if row.kind == "suspected_hallucinated_references"]) == 1
        with board.read() as conn:
            assert conn.scalar(select(func.count()).select_from(effects).where(effects.c.store_id == board.scope.require_store_id())) == 0
