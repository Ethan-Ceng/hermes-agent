"""Ordinary compute resolves its Profile at the owner; child claims remain read-only."""

from contextlib import closing
from types import SimpleNamespace
import uuid

import pytest

from gateway.session_worker_kanban import worker_kanban
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_cli.db_sessions import open_session_store
from hermes_db.integration.kanban_wire import pack, unpack
from hermes_db.domains.runtime.access import runtime_for_store
from hermes_state_keys import admission_fingerprint
from hermes_state_runtime import RuntimeStoreError

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def setup_owner(home, db, monkeypatch):
    db.create_session("interactive", "cli")
    runtime = runtime_for_store(db)
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.register_worker(epoch=epoch, execution_id="compute", session_id="interactive", generation=0,
                            kind="compute", adoption_secret="verified")
    runtime.adopt_worker(epoch=epoch, execution_id="compute", session_id="interactive", generation=0, adoption_secret="verified")
    authority = SimpleNamespace(db=db, epoch=epoch, profile_id=str(home), runner=object(),
        sessions={"interactive": SimpleNamespace(source=object())}, logical_owner=lambda sid: sid)
    connection = SimpleNamespace(authority=authority, actor=SimpleNamespace(subject="producer", profile_id=str(home),
        capabilities={"worker:adopt"}))
    monkeypatch.setattr("gateway.session_policy.policy_for_source", lambda *args: None)
    monkeypatch.setattr("gateway.session_worker._claim", lambda connection, ref, params: "verified")
    scope = dict(profile_id=str(home), session_id="interactive", execution_id="compute", generation=0,
                 pid=123, birth=1.0, secret="private-claim-proof", epoch=epoch)
    return runtime, connection, scope


async def call(connection, scope, operation, args=(), kwargs=None, *, target=None, command=False, command_id=None):
    payload = {"args": pack(args), "kwargs": pack(kwargs or {})}
    if target is not None:
        payload["target"] = target
    params = dict(scope, operation=operation, payload=payload)
    if operation == "board.resolve":
        params["payload"] = {"board": kwargs.get("board") if kwargs else None}
    if command:
        params["command_id"] = command_id or uuid.uuid4().hex
    return unpack(await worker_kanban(connection, None, params, command=command))


@pytest.mark.asyncio
async def test_interactive_resolution_first_write_receipt_and_child_reads(pg_profiles, monkeypatch):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.domains.kanban.postgres.catalog import _lookup
    from hermes_db.domains.runtime.postgres.operations.worker_children import reservation_effect
    with pg_profiles("one") as home, closing(open_session_store(home / "state.db")) as db:
        runtime, connection, scope = setup_owner(home, db, monkeypatch)
        context = await call(connection, scope, "board.resolve")
        target = {"board": "default", "board_id": context["owner"]["board_id"]}
        assert await call(connection, scope, "list_tasks", target=target) == []
        with acquire_profile_domain("kanban_tasks") as resource, resource.read() as conn:
            assert _lookup(conn, resource, "default") is None
        command_id = uuid.uuid4().hex
        task = await call(connection, scope, "create_task", kwargs={"title": "interactive\x00🙂"},
                          target=target, command=True, command_id=command_id)
        assert await call(connection, scope, "create_task", kwargs={"title": "interactive\x00🙂"},
                          target=target, command=True, command_id=command_id) == task
        await call(connection, scope, "add_notify_sub", kwargs={"task_id": task, "platform": "telegram", "chat_id": "chat"},
                   target=target, command=True)
        identity = {key: scope[key] for key in ("profile_id", "pid", "birth")}
        secret = "child-private-proof"
        child = runtime.apply_worker_receipt(epoch=scope["epoch"], execution_id="compute", session_id="interactive", generation=0,
            sequence=1, operation="child.reserve", payload={"secret": secret}, handlers={"child.reserve": reservation_effect(
                epoch=scope["epoch"], execution_id="compute", identity=identity, principal="producer", limits=(1, 1))})["child"]
        child_scope = dict(scope, **child, secret=secret)
        child_claim = admission_fingerprint(canonical_target=child["session_id"], payload={
            **identity, **child, "secret": secret, "principal": "producer"})
        monkeypatch.setattr("gateway.session_worker._claim", lambda connection, ref, params:
                            child_claim if "/child:" in params["execution_id"] else "verified")
        assert (await call(connection, child_scope, "board.resolve"))["owner"] == context["owner"]
        assert (await call(connection, child_scope, "get_task", (task,), target=target)).title == "interactive\x00🙂"
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            await call(connection, child_scope, "add_comment", (task, "child", "forbidden"), target=target, command=True)
        with pytest.raises(RuntimeStoreError, match="invalid_params"):
            await call(connection, scope, "get_task", (task,), target=target | {"profile_home": "forbidden"})
        with pytest.raises(RuntimeStoreError, match="stale_generation"):
            await call(connection, scope, "get_task", (task,), target=target | {"board_id": "wrong"})
    with pg_profiles("one"), kbc.connect_closing() as reopened:
        assert [row.id for row in kb.list_tasks(reopened)] == [task]
        assert kb.list_comments(reopened, task) == []
    with pg_profiles("two"), kbc.connect_closing() as other:
        assert kb.list_tasks(other) == []
