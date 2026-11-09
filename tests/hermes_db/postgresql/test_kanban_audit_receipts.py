"""A committed refusal audit and its exact RPC error survive an unknown commit."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_db.domains.kanban.api import BoardResource
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.kanban.postgres.receipts import CommandReceipt, CommandReplay

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@contextmanager
def lose_audit_ack(board, monkeypatch):
    from hermes_db.domains.kanban.postgres import repository as repo
    dialect, armed = board._transactions.engine.dialect, []
    commit, event = dialect.do_commit, repo.event
    def observed(conn, store, task_id, kind, *args, **kwargs):
        result = event(conn, store, task_id, kind, *args, **kwargs)
        if kind.startswith("completion_blocked_"):
            armed.append(True)
        return result
    def lose(connection):
        commit(connection)
        if armed:
            raise OperationalError("refusal audit COMMIT acknowledgement lost", None, None)
    with monkeypatch.context() as patch:
        patch.setattr(repo, "event", observed)
        patch.setattr(dialect, "do_commit", lose)
        yield
    assert armed


@pytest.mark.parametrize("error_name", ["EmptyCompletionError", "HallucinatedCardsError"])
def test_refusal_audit_replays_original_error_after_task_has_completed(pg_profiles, monkeypatch, error_name):
    with pg_profiles("one"), kbc.connect_closing() as board:
        task = kb.create_task(board, title="evidence required", workspace_kind="scratch")
        kwargs = {"summary": "proof", "created_cards": ["t_deadbeef"]} if error_name == "HallucinatedCardsError" else {}
        command_id = uuid4().hex
        with BoardResource(board, board.board_id, board.slug, command=CommandReceipt(command_id, "frozen")) as first:
            with lose_audit_ack(board, monkeypatch), pytest.raises(UnknownCommitError):
                kb.complete_task(first, task, **kwargs)
        assert kb.complete_task(board, task, summary="operator supplied evidence")
        with BoardResource(board, board.board_id, board.slug, command=CommandReceipt(command_id, "frozen")) as retry:
            with pytest.raises(CommandReplay) as replay:
                kb.complete_task(retry, task, **kwargs)
            assert replay.value.result.name == error_name
            with pytest.raises(getattr(kb, error_name)):
                replay.value.result.raise_error()
        assert len([row for row in kb.list_events(board, task) if row.kind.startswith("completion_blocked_")]) == 1
        assert kb.get_task(board, task).status == "done"
