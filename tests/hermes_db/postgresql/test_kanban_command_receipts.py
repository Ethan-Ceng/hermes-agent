"""Real COMMIT loss replays the exact result without a second Board effect."""
from hermes_db.domains.kanban import rules as kanban_rules

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Barrier

import pytest
from sqlalchemy.exc import OperationalError

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_db.domains.kanban.api import BoardResource
from hermes_db.errors import UnknownCommitError
from hermes_db.domains.kanban.postgres.receipts import CommandReceipt, CommandReplay
from hermes_state_runtime import RuntimeStoreError

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_lost_commit_ack_replays_comment_identity_and_rejects_changed_command(pg_profiles, monkeypatch):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="command", workspace_kind="scratch")
        command_id = uuid.uuid4().hex
        engine = store._transactions.engine
        commit = engine.dialect.do_commit

        def lose_ack(connection):
            commit(connection)
            raise OperationalError("commit acknowledgement lost", None, None)

        with BoardResource(store, store.board_id, store.slug, command=CommandReceipt(command_id, "frozen")) as command:
            with monkeypatch.context() as patch:
                patch.setattr(engine.dialect, "do_commit", lose_ack)
                with pytest.raises(UnknownCommitError):
                    kb.add_comment(command, task_id, "worker", "exact\x00🙂")
        comments = kb.list_comments(store, task_id)
        assert len(comments) == 1 and comments[0].body == "exact\x00🙂"
        assert engine.pool.checkedout() == 0
        with BoardResource(store, store.board_id, store.slug, command=CommandReceipt(command_id, "frozen")) as retry:
            with pytest.raises(CommandReplay) as replay:
                kb.add_comment(retry, task_id, "worker", "exact\x00🙂")
            assert replay.value.result == comments[0].id
        with BoardResource(store, store.board_id, store.slug, command=CommandReceipt(command_id, "changed")) as changed:
            with pytest.raises(RuntimeStoreError, match="admission_conflict"):
                kb.add_comment(changed, task_id, "worker", "different")
        assert len(kb.list_comments(store, task_id)) == 1


def test_receipt_write_failure_rolls_back_business_effect(pg_profiles, monkeypatch):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="atomic", workspace_kind="scratch")
        receipt = CommandReceipt(uuid.uuid4().hex, "frozen")

        def fail(*args):
            raise RuntimeError("receipt write failed")

        with BoardResource(store, store.board_id, store.slug, command=receipt) as command:
            monkeypatch.setattr(receipt, "record", fail)
            with pytest.raises(RuntimeError, match="receipt write failed"):
                kb.add_comment(command, task_id, "worker", "must roll back")
        assert kb.list_comments(store, task_id) == []
        assert not any(event.kind == "commented" for event in kb.list_events(store, task_id))


def test_command_identity_is_scoped_to_board_and_store(pg_profiles, monkeypatch):
    monkeypatch.setattr(kanban_rules, "_new_task_id", lambda: "t_same")
    command_id = uuid.uuid4().hex
    for profile, board in (("one", "alpha"), ("one", "beta"), ("two", "alpha")):
        with pg_profiles(profile):
            kb.create_board(board)
            with kbc.connect_closing(board=board) as store:
                task_id = kb.create_task(store, title=board, workspace_kind="scratch")
                with BoardResource(store, store.board_id, store.slug, command=CommandReceipt(command_id, "frozen")) as command:
                    kb.add_comment(command, task_id, "worker", f"{profile}/{board}")
                assert [row.body for row in kb.list_comments(store, task_id)] == [f"{profile}/{board}"]


def test_competing_connections_apply_same_command_only_once(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="concurrent receipt", workspace_kind="scratch")
        command_id = uuid.uuid4().hex
        gate = Barrier(3)

        def write():
            with BoardResource(store, store.board_id, store.slug, command=CommandReceipt(command_id, "frozen")) as command:
                gate.wait(timeout=10)
                try:
                    return kb.add_comment(command, task_id, "worker", "exactly once")
                except CommandReplay as replay:
                    return replay.result

        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [workers.submit(copy_context().run, write) for _ in range(2)]
            gate.wait(timeout=10)
            ids = [future.result(timeout=15) for future in pending]
        comments = kb.list_comments(store, task_id)
        assert ids == [comments[0].id, comments[0].id] and len(comments) == 1
