"""Ordinary local creation atomically commits its frozen policy, route and row."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json

import pytest


def _receipt(store):
    from gateway.session_worker_construct import StagedReceipt
    from hermes_db.health import profile_home_for_store
    from hermes_state_keys import local_identity
    profile = str(profile_home_for_store(store))
    sid = local_identity(profile, "principal", "request")
    route = "agent:main:local:dm:" + sid
    return StagedReceipt(profile_id=profile, principal_id="principal", request_id="request", session_id=sid, route=route,
        policy=dict(source="cli", model="model", cwd=profile, request_json=json.dumps({"source": "cli", "request_id": "request"})),
        entry=dict(session_id=sid, session_key=route, created_at=datetime.now().isoformat(),
            origin={"platform": "local", "chat_id": sid, "user_id": "principal"}))


def test_local_create_retry_keeps_the_original_policy_route_and_prompt_prefix(store, runtime):
    from hermes_db.integration.local_access import commit_local_session, local_receipt, handoff_head
    from hermes_state_runtime import RuntimeStoreError
    epoch = runtime.begin_epoch(instance_id="owner")
    receipt = _receipt(store)
    sid = receipt["session_id"]
    first = commit_local_session(store, epoch=epoch, receipt=receipt)
    store.update_system_prompt(sid, "cached\x00prefix")
    store.append_message(sid, "user", "first turn")
    assert commit_local_session(store, epoch=epoch, receipt=receipt) == first
    assert local_receipt(store, sid)["route"] == receipt["route"]
    assert store.load_gateway_routing_entries()[receipt["route"]]
    assert store.get_session(sid)["created_source"] == "cli"
    assert store.get_session(sid)["system_prompt"] == "cached\x00prefix"
    assert handoff_head(store, sid) == (sid, sid)
    changed = deepcopy(receipt)
    changed["policy"]["request_json"] = json.dumps({"source": "tui", "request_id": "request"})
    with pytest.raises(RuntimeStoreError, match="invalid_params"):
        commit_local_session(store, epoch=epoch, receipt=changed)


def test_idle_close_shares_fifo_idleness_and_new_work_does_not_disappear(store, runtime):
    from hermes_db.integration.local_access import commit_local_session, end_idle_local_session
    epoch = runtime.begin_epoch(instance_id="owner")
    receipt = _receipt(store)
    sid = receipt["session_id"]
    commit_local_session(store, epoch=epoch, receipt=receipt)
    runtime.admit_input(epoch=epoch, principal_id="principal", session_id=sid, request_id="input", payload={"text": "ask"})
    assert end_idle_local_session(store, epoch=epoch, session_id=sid, target_id=sid, reason="ws_orphan_reap") == 0
    assert store.get_session(sid)["ended_at"] is None


@pytest.mark.parametrize("old", ["alpha", "main"])
def test_native_profile_rename_keeps_local_creation_identity_and_frozen_prefix(core_pair, old):
    from hermes_db.health import persisted_profile_id
    from hermes_db.integration.local_access import commit_local_session, local_receipt, validate_local_lineage
    from hermes_db.integration.runtime_access import runtime_for_store
    from hermes_state_keys import local_identity
    from gateway.session import _session_key_namespace
    from types import SimpleNamespace
    store, other = core_pair
    receipt = _receipt(store)
    receipt["profile_id"] = persisted_profile_id(SimpleNamespace(db=store))
    sid = local_identity(receipt["profile_id"], receipt["principal_id"], receipt["request_id"])
    route = _session_key_namespace(old) + ":local:dm:" + sid
    receipt.update(session_id=sid, route=route)
    receipt["entry"].update(session_id=sid, session_key=route)
    receipt["entry"]["origin"].update(chat_id=sid, profile=old)
    runtime = runtime_for_store(store)
    epoch = runtime.begin_epoch(instance_id="owner")
    commit_local_session(store, epoch=epoch, receipt=receipt)
    store.update_system_prompt(sid, "frozen prompt")
    store.rekey_profile_state(old, "beta")
    renamed = local_receipt(store, sid)
    assert renamed["profile_id"] == receipt["profile_id"] and renamed["session_id"] == sid
    assert renamed["route"] == "agent:beta:local:dm:" + sid
    assert renamed["entry"]["session_key"] == renamed["route"]
    assert renamed["entry"]["origin"]["profile"] == "beta"
    assert renamed["policy"] == receipt["policy"]
    validate_local_lineage(store, renamed)
    assert store.get_session(sid)["system_prompt"] == "frozen prompt"
    assert other.get_session(sid) is None


def test_core_unknown_create_ack_preserves_published_prefill_and_replays_receipt(core_pair, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.integration.local_access import commit_local_session
    from hermes_db.integration.runtime_access import runtime_for_store
    store = core_pair[0]
    receipt = _receipt(store)
    epoch = runtime_for_store(store).begin_epoch(instance_id="owner")
    events = []

    class Publication:
        def read(self):
            events.append("read")

        def publish(self):
            events.append("publish")

        def withdraw(self):
            events.append("withdraw")

    receipt.on_create = Publication()
    write = store._context.write

    @contextmanager
    def lost_ack():
        with write() as conn:
            yield conn
        raise UnknownCommitError("injected committed acknowledgement loss")

    with monkeypatch.context() as patch:
        patch.setattr(store._context, 'write', lost_ack)
        with pytest.raises(UnknownCommitError):
            commit_local_session(store, epoch=epoch, receipt=receipt)
    assert store.get_session(receipt["session_id"]) is not None and events == ["read", "publish"]
    commit_local_session(store, epoch=epoch, receipt=receipt)
    assert events == ["read", "publish", "read"]
