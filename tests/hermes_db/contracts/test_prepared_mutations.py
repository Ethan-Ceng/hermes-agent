"""Prepared policy edits revalidate their target while preserving prompt prefixes."""

from copy import deepcopy
import json

import pytest

from hermes_state_runtime import RuntimeStoreError


def local_setup(store):
    from datetime import UTC, datetime
    from gateway.config import Platform
    from gateway.session import SessionEntry, SessionSource, build_session_key
    from hermes_state import SessionDB
    from hermes_state_keys import local_identity
    from hermes_state_local import POLICY_PREFIX

    sid = local_identity("owned", "human", "local")
    source = SessionSource(Platform.LOCAL, sid, user_id="human", chat_type="dm", profile="owned")
    route = build_session_key(source)
    store.create_session(sid, "cli", model="old-model", system_prompt="exact\x00prefix", user_id="human", session_key=route, chat_id=sid)
    now = datetime.now(UTC)
    entry = SessionEntry(route, sid, now, now, origin=source, platform=Platform.LOCAL)
    policy = dict(source="cli", model="old-model", cwd="/old", config_json=json.dumps({"model": {"provider": "old-provider"}}))
    receipt = dict(session_id=sid, profile_id="owned", principal_id="human", request_id="local", route=route,
                   entry=entry.to_dict(), lineage=[sid], policy=policy)
    if isinstance(store, SessionDB):
        store.set_meta(POLICY_PREFIX + sid, json.dumps(receipt))
    else:
        from hermes_db.domains.runtime.postgres.queries import runtime
        with store._write() as conn:
            runtime.set_meta(conn, store.scope, POLICY_PREFIX + sid, json.dumps(receipt))
    store.save_gateway_routing_entry(route, json.dumps(entry.to_dict()))
    return sid, receipt


def test_prepared_model_pick_keeps_prompt_tools_and_transcript_exact(store, runtime):
    sid, receipt = local_setup(store)
    store.append_message(sid, "user", "held\x00input")
    store.update_session_tool_names(sid, ["tool"])
    before = store.get_session(sid)
    messages = store.get_messages(sid)
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id=sid, request_id="model", expected_revision=before["runtime_revision"],
        expected_generation=before["runtime_generation"], operation="model", payload={"model": "new-model", "provider": "new-provider"})
    snapshot = runtime.mutate_session(**args, _prepare_only=True)["snapshot"]
    policy = deepcopy(receipt["policy"])
    policy.update(model="new-model", config_json=json.dumps({"model": {"provider": "new-provider"}}))
    result = runtime.mutate_session(**args, _prepared={"snapshot": snapshot, "policy": policy})
    assert result["model"] == "new-model" and result["execution_generation"] == before["runtime_generation"] + 1
    row = store.get_session(sid)
    assert row["system_prompt"] == before["system_prompt"] and row["tool_names"] == before["tool_names"]
    assert store.get_messages(sid) == messages
    assert runtime.mutate_session(**args, _prepared={}) == result


def test_prepared_policy_staleness_rolls_back_generation_and_workspace(store, runtime):
    sid, receipt = local_setup(store)
    before = store.get_session(sid)
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id=sid, request_id="workspace", expected_revision=before["runtime_revision"],
        operation="workspace", payload={"cwd": "/new"})
    snapshot = runtime.mutate_session(**args, _prepare_only=True)["snapshot"]
    runtime.mutate_session(epoch=epoch, principal_id="human", session_id=sid, request_id="rename", expected_revision=before["runtime_revision"],
        operation="rename", payload={"title": "new revision"})
    with pytest.raises(RuntimeStoreError, match="revision_conflict"):
        runtime.mutate_session(**args, _prepared={"snapshot": snapshot, "policy": receipt["policy"], "git": {"branch": "main", "root": "/new"}})
    assert store.get_session(sid)["runtime_generation"] == before["runtime_generation"]
    assert store.get_session(sid)["cwd"] == before["cwd"]
