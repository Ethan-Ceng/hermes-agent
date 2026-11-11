"""The ordinary API binding owns its route, source and declared key in native storage."""

from types import SimpleNamespace

import pytest



def test_native_api_binding_is_scoped_idempotent_and_keeps_declared_ownership(api_owner):
    from gateway.session_api import bind_api_session, declared_api_session, restore_api_session
    from hermes_state_runtime import RuntimeStoreError
    authority, db, other = api_owner
    home = db.scope.profile_home
    try:
        ref = bind_api_session(authority, "api-id", declared_key="declared")
        assert ref.session_id == "api-id"
        db.append_message("api-id", "user", "retained")
        assert bind_api_session(authority, "api-id", declared_key="declared") == ref
        assert declared_api_session(db, "declared") == "api-id"
        assert restore_api_session(authority, "api-id") == ref
        assert db.get_messages_as_conversation("api-id")[0]["content"] == "retained"
        with pytest.raises(RuntimeStoreError, match="admission_conflict"):
            bind_api_session(authority, "another", declared_key="declared")
        assert db.get_session("another") is None
        assert other.get_session("api-id") is None
        assert not (home / "state.db").exists()
    finally:
        authority.sessions.clear()


def test_native_api_admission_replays_and_refuses_retargeted_client_key(api_owner):
    from gateway.session_api_turn import admit_api_turn, api_settings
    from hermes_state_runtime import RuntimeStoreError
    owner, db, other = api_owner
    from hermes_db.domains.runtime.access import runtime_for_store
    adapter = SimpleNamespace(gateway_runner=owner.runner, _ensure_session_db=lambda: db,
        _model_routes={}, _model=None, _model_provider=None)
    owner.runner._adapter_for_source = lambda source: adapter
    args = dict(session_id="api-turn", request_id="client-key", user_message="hello",
        conversation_history=[], requested_model="test-model")
    first = admit_api_turn(adapter, **args)
    assert first[2]["status"] == "queued"
    assert admit_api_turn(adapter, **args)[2]["admission_id"] == first[2]["admission_id"]
    assert api_settings(owner, first[1])["requested_model"] == "test-model"
    with pytest.raises(RuntimeStoreError, match="admission_conflict"):
        admit_api_turn(adapter, **{**args, "session_id": "other-target"})
    assert len(runtime_for_store(db).list_admissions(session_id="api-turn")) == 1
    assert other.get_meta("gateway.api.settings.v1.api-turn") is None


def test_deleted_native_api_generation_replays_its_original_terminal_identity(api_owner):
    from gateway.session_api import api_generation_id, implicit_api_session
    from gateway.session_api_turn import admit_api_turn
    from hermes_db.domains.runtime.access import runtime_for_store
    owner, db, _other = api_owner
    adapter = SimpleNamespace(gateway_runner=owner.runner, _ensure_session_db=lambda: db, _model_routes={})
    owner.runner._adapter_for_source = lambda source: adapter
    args = dict(session_id="opening", request_id="retained-key", user_message="hello", conversation_history=[])
    first = admit_api_turn(adapter, **args)[2]
    runtime = runtime_for_store(db)
    claim = runtime.claim_input(epoch=owner.epoch, session_id="opening")
    runtime.settle_input(epoch=owner.epoch, admission_id=claim["admission_id"], generation=claim["generation"],
        outcome="completed")
    assert db.delete_session("opening")
    assert implicit_api_session(db, "opening", "retained-key") == "opening"
    assert implicit_api_session(db, "opening", "new-key") == api_generation_id("opening", 1)
    assert admit_api_turn(adapter, **args)[2]["admission_id"] == first["admission_id"]
    assert db.get_session("opening") is None
