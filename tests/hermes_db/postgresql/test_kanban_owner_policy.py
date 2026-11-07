"""Assigned session owners resolve the Board's captured Profile, never their own store_id."""

import json
from types import SimpleNamespace

import pytest

from gateway.session_contract import SessionActor
from gateway.session_kanban import build_kanban_policy
from gateway.session_kanban_policy import admit_postgresql_claim
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from hermes_db.domains.kanban_owner import board_reference, open_board_owner
from hermes_db.errors import StorageConfigurationError
from hermes_db.operations import kanban_owner
from hermes_state_runtime import RuntimeStoreError

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_assigned_owner_freezes_pg_board_policy_and_writes_exact_receipt(pg_profiles, tmp_path, monkeypatch):
    with pg_profiles("one"), kbc.connect_closing() as store:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        task_id = kb.create_task(store, title="managed policy", assignee="coder", workspace_kind="dir",
                                 workspace_path=str(workspace), model_override="test-model", provider_override="custom")
        task = kb.claim_task(store, task_id)
        params = dict(board=store.slug, task_id=task.id, run_id=task.current_run_id, claim_lock=task.claim_lock,
                      owner=board_reference(store))
    with pg_profiles("two") as assigned:
        monkeypatch.setattr("hermes_cli.profiles.resolve_profile_env", lambda name: str(assigned))
        actor = SessionActor("owner", str(assigned), frozenset({"session:create"}), "transport")
        connection = SimpleNamespace(authority=SimpleNamespace(profile_id=str(assigned)), actor=actor, native_owner=True)
        config = {"model": {"default": "test-model", "provider": "custom"}, "platform_toolsets": {"cli": ["terminal"]}}
        policy, _private = build_kanban_policy(connection, params, config)
        context = json.loads(policy.kanban_json)
        assert context["owner"] == params["owner"] and "db" not in context
        assert context["workspace"] == str(workspace) and "managed policy" in context["context"]
        assert context["owner"]["store_id"] == "one"
        receipt = {"storage_backend": "postgresql", "profile_home": str(assigned), "store_id": "two",
                   "principal_id": "owner", "session_id": "session", "request_id": "request"}
        admit_postgresql_claim(context, params, receipt)
        admit_postgresql_claim(context, params, receipt)
        with open_board_owner(context["owner"]) as board:
            events = [event for event in kb.list_events(board, task_id) if event.kind == "owner_admitted"]
            assert len(events) == 1 and events[0].payload["store_id"] == "two"
            assert kanban_owner.bind_worker(board, params, pid=123, fingerprint="verified") > 0
            assert kanban_owner.bound_claim_live(board, params, pid=123)
            assert not kanban_owner.bound_claim_live(board, params, pid=456)
            kanban_owner.record_result(board, params, pid=456, code=0, last_output="forged")
            assert kanban_owner.worker_result(board, params) == {}
            kanban_owner.record_result(board, params, pid=123, code=7, last_output="persisted")
            assert kanban_owner.worker_result(board, params)["last_output"] == "persisted"
            assert kb.block_task(board, task_id, reason="superseded", expected_run_id=task.current_run_id)
            kanban_owner.record_loss(board, params, "late loss", pid=123)
            assert not any(event.kind == "worker_lost" for event in kb.list_events(board, task_id))
        for changed in ({"owner": params["owner"] | {"store_id": "two"}}, {"claim_lock": "forged"}, {"cwd": str(workspace)}):
            with pytest.raises(RuntimeStoreError):
                build_kanban_policy(connection, params | changed, config)


def test_owner_reference_refuses_retired_generation_and_backend_fallback(pg_profiles):
    with pg_profiles("one"):
        kb.create_board("named")
        with kbc.connect_closing(board="named") as store:
            reference = board_reference(store)
        kb.remove_board("named", archive=True)
        kb.create_board("named")
        with pytest.raises(StorageConfigurationError, match="generation"):
            with open_board_owner(reference):
                pytest.fail("stale generation opened")
        with pytest.raises(StorageConfigurationError, match="reference"):
            with open_board_owner(reference | {"dsn": "forbidden"}):
                pytest.fail("caller supplied connection details accepted")
