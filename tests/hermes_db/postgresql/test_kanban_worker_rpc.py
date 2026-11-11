"""Actual owner SDK fences, separate Board owner and closed mutation receipt semantics."""

from contextlib import closing
import json
import uuid
from types import SimpleNamespace

import pytest

from gateway.session_worker_kanban import worker_kanban
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_cli.db_sessions import open_session_store
from hermes_db.domains.kanban.owner import board_reference
from hermes_cli.kanban_storage_wire import CommandRefusal, pack, unpack
from hermes_db.domains.runtime.access import runtime_for_store
from hermes_state_runtime import RuntimeStoreError

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.asyncio
async def test_board_rpc_uses_frozen_owner_and_actual_worker_generation_ledger(pg_profiles, monkeypatch):
    with pg_profiles("one"), kbc.connect_closing() as board:
        task_id = kb.create_task(board, title="RPC", workspace_kind="scratch", assignee="coder")
        task = kb.claim_task(board, task_id)
        context = dict(owner=board_reference(board), task_id=task_id, run_id=task.current_run_id, claim_lock=task.claim_lock)
    with pg_profiles("two") as home, closing(open_session_store(home / "state.db")) as db:
        db.create_session("session", "kanban")
        runtime = runtime_for_store(db)
        epoch = runtime.begin_epoch(instance_id="owner")
        runtime.register_worker(epoch=epoch, execution_id="worker", session_id="session", generation=0,
                                kind="kanban", adoption_secret="verified")
        runtime.adopt_worker(epoch=epoch, execution_id="worker", session_id="session", generation=0, adoption_secret="verified")
        authority = SimpleNamespace(db=db, epoch=epoch, profile_id=str(home), runner=object(),
            sessions={"session": SimpleNamespace(source=object())}, logical_owner=lambda sid: sid)
        connection = SimpleNamespace(authority=authority, actor=SimpleNamespace(profile_id=str(home), subject="producer",
                                     capabilities={"worker:adopt"}))
        monkeypatch.setattr("gateway.session_worker._claim", lambda *args: "verified")
        policy = SimpleNamespace(source="kanban", kanban_json=json.dumps(context))
        monkeypatch.setattr("gateway.session_policy.policy_for_source", lambda *args: policy)
        scope = dict(profile_id=str(home), session_id="session", execution_id="worker", generation=0,
                     pid=123, birth=1.0, secret="verified-client-proof", epoch=epoch)
        payload = {"args": pack([task_id]), "kwargs": pack({"author": "worker", "body": "committed\x00🙂"})}
        command = dict(scope, operation="add_comment", command_id=uuid.uuid4().hex, payload=payload)
        first = unpack(await worker_kanban(connection, None, command, command=True))
        assert unpack(await worker_kanban(connection, None, command, command=True)) == first
        altered = dict(command, payload={"args": pack([task_id]), "kwargs": pack({"author": "worker", "body": "changed"})})
        with pytest.raises(RuntimeStoreError, match="admission_conflict"):
            await worker_kanban(connection, None, altered, command=True)
        read = dict(scope, operation="get_task", payload={"args": pack([task_id]), "kwargs": pack({})})
        assert unpack(await worker_kanban(connection, None, read, command=False)).title == "RPC"
        for rejected in (dict(read, operation="sql"), dict(read, operation="add_comment"), dict(read, owner=context["owner"]),
                         dict(read, payload={"args": pack([task_id]), "kwargs": pack({"db_path": "forbidden"})})):
            with pytest.raises(RuntimeStoreError, match="invalid_params"):
                await worker_kanban(connection, None, rejected, command=False)
        empty = dict(command, command_id=uuid.uuid4().hex,
                     payload={"args": pack([task_id]), "kwargs": pack({"author": "worker", "body": ""})})
        refusal = unpack(await worker_kanban(connection, None, empty, command=True))
        assert isinstance(refusal, CommandRefusal)
        with pytest.raises(ValueError, match="body is required"):
            refusal.raise_error()
        with pytest.raises(RuntimeStoreError, match="stale_generation|permission_denied"):
            await worker_kanban(connection, None, command | {"generation": 99}, command=True)
        authority.epoch = runtime.begin_epoch(instance_id="replacement")
        with pytest.raises(RuntimeStoreError, match="stale_epoch|stale_generation"):
            await worker_kanban(connection, None, command, command=True)
    with pg_profiles("one"), kbc.connect_closing() as board:
        assert [row.body for row in kb.list_comments(board, task_id)] == ["committed\x00🙂"]
