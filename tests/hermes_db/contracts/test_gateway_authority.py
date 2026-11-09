"""The ordinary gateway owner can create and recover current native local sessions."""

from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest


def test_persisted_identity_needs_only_the_stable_store_scope(tmp_path):
    from hermes_db.health import persisted_profile_id
    from hermes_db.scope import DatabaseScope
    first = SimpleNamespace(db=SimpleNamespace(scope=DatabaseScope(tmp_path / "a", "same-store")))
    second = SimpleNamespace(db=SimpleNamespace(scope=DatabaseScope(tmp_path / "b", "same-store")))
    different = SimpleNamespace(db=SimpleNamespace(scope=DatabaseScope(tmp_path / "b", "other-store")))
    assert persisted_profile_id(first) == persisted_profile_id(second)
    assert persisted_profile_id(first) != persisted_profile_id(different)


@asynccontextmanager
async def _owner_at(db, monkeypatch, instance):
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_contract import SessionActor
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    home = db.scope.profile_home
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("platform_toolsets: {cli: []}\nmodel: {provider: custom, default: m, base_url: http://x.invalid/v1}\n")
    token = set_hermes_home_override(home)
    monkeypatch.setattr(SessionStore, "_open_session_db_for_active_scope", lambda self, **kw: db)
    try:
        store = SessionStore(home / "sessions", GatewayConfig())
        store._db = db
        runner = SimpleNamespace(session_store=store, _session_db=db, adapters={}, _draining=False,
            _cached_agent_for=lambda route: None, _adapter_for_source=lambda source: None, _evict_cached_agent=lambda route: None)
        owner = await initialize_session_authority(runner, profile_id=str(home), instance_id=instance)
        actor = SessionActor("principal", str(home), frozenset({"session:create", "session:read", "session:control"}), "test")
        yield owner, actor
    finally:
        reset_hermes_home_override(token)


@pytest.mark.asyncio
async def test_pg_create_retry_uses_stable_store_identity_across_local_homes(core_pair, tmp_path, monkeypatch):
    from gateway.session_local import create_local_session
    from gateway.session_contract import SessionRef
    from gateway.session_mutations import mutate_session
    from hermes_db.scope import DatabaseScope
    from hermes_db.session_store import PostgresSessionStore
    original, other = core_pair
    second = PostgresSessionStore(original._transactions,
        DatabaseScope(tmp_path / "another-node", original.scope.store_id))
    args = dict(request_id="same-create", source="cli", cwd=str(original.scope.profile_home), toolsets=[])
    try:
        async with _owner_at(original, monkeypatch, "first") as (owner, actor):
            first_ref = create_local_session(owner, actor, args)
            original.append_message(first_ref.session_id, "user", "retained")
            original.create_session("imported", "import", user_id=actor.subject)
            await mutate_session(owner, actor, SessionRef(owner.profile_id, "imported"),
                dict(session_id="imported", request_id="bind", expected_revision=0,
                     operation="rename", payload={"title": "first owner"}))
        async with _owner_at(second, monkeypatch, "second") as (owner, actor):
            replay = create_local_session(owner, actor, args)
            assert replay.session_id == first_ref.session_id
            assert replay.profile_id != first_ref.profile_id  # Public authorization remains local to its server mapping.
            assert second.get_messages_as_conversation(replay.session_id)[0]["content"] == "retained"
            current = second.get_session("imported")
            await mutate_session(owner, actor, SessionRef(owner.profile_id, "imported"),
                dict(session_id="imported", request_id="second-node", expected_revision=current["runtime_revision"],
                     operation="rename", payload={"title": "same owner"}))
            assert second.get_session_title("imported") == "same owner"
        async with _owner_at(other, monkeypatch, "other") as (owner, actor):
            different = create_local_session(owner, actor, args)
            assert different.session_id != first_ref.session_id
            assert other.get_session(first_ref.session_id) is None
    finally:
        second.close()


@pytest.mark.asyncio
async def test_native_resume_refreshes_settings_without_rewriting_prompt_or_history(core_pair, monkeypatch):
    import json
    from gateway.session_local import create_local_session
    from gateway.session_policy_refresh import commit_refresh
    from hermes_db.integration.local_access import local_receipt
    db, _other = core_pair
    async with _owner_at(db, monkeypatch, "refresh-owner") as (owner, actor):
        home = db.scope.profile_home
        ref = create_local_session(owner, actor, dict(request_id="create-refresh", source="cli", cwd=str(home), toolsets=[]))
        db.update_system_prompt(ref.session_id, "frozen prompt")
        db.append_message(ref.session_id, "user", "retained history")
        before = db.get_messages_as_conversation(ref.session_id)
        (home / "config.yaml").write_text("platform_toolsets: {cli: []}\nmodel: {provider: custom, default: refreshed, base_url: http://x.invalid/v1}\nagent: {max_turns: 31}\n")
        monkeypatch.setattr(owner, "_schedule", lambda ref: None)
        assert await commit_refresh(owner, ref)
        policy = local_receipt(db, ref.session_id)["policy"]
        assert policy["model"] == "m"
        assert json.loads(policy["config_json"])["agent"]["max_turns"] == 31
        assert db.get_session(ref.session_id)["system_prompt"] == "frozen prompt"
        assert db.get_messages_as_conversation(ref.session_id) == before


@pytest.mark.asyncio
async def test_native_owner_creates_and_recovers_local_policy_without_sqlite(core_pair, monkeypatch):
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_contract import SessionActor, Submission
    from gateway.session_local import create_local_session
    from gateway.session_mutations import mutate_session
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_state_local import POLICY_PREFIX
    from hermes_state_mutation_binding import BINDING_PREFIX
    from hermes_state_runtime import RuntimeStoreError
    from gateway.session_history_mount import mount_history, require_history_leaf
    db = core_pair[0]
    home = db.scope.profile_home
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("platform_toolsets: {cli: []}\nmodel: {provider: custom, default: m, base_url: http://x.invalid/v1}\n")
    token = set_hermes_home_override(home)
    monkeypatch.setattr(SessionStore, "_open_session_db_for_active_scope", lambda self, **kw: db)

    def runner():
        store = SessionStore(home / "sessions", GatewayConfig())
        store._db = db
        return SimpleNamespace(session_store=store, _session_db=db, adapters={}, _draining=False,
            _cached_agent_for=lambda route: None, _adapter_for_source=lambda source: None, _evict_cached_agent=lambda route: None)

    try:
        owner = await initialize_session_authority(runner(), profile_id=str(home), instance_id="first")
        actor = SessionActor("principal", str(home), frozenset({"session:create", "session:read", "session:control", "session:submit"}), "test")
        args = {"request_id": "create", "source": "cli", "cwd": str(home), "toolsets": []}
        ref = create_local_session(owner, actor, args)
        owner.authorize(actor, ref, "session:read")
        frozen = db.get_meta(POLICY_PREFIX + ref.session_id)
        assert frozen is not None
        row = db.get_session(ref.session_id)
        rename = dict(session_id=ref.session_id, request_id="rename", expected_revision=row["runtime_revision"],
                      operation="rename", payload={"title": "renamed"})
        first = await mutate_session(owner, actor, ref, rename)
        assert await mutate_session(owner, actor, ref, rename) == first
        assert db.get_session_title(ref.session_id) == "renamed"
        db.create_session("imported", "import", user_id=actor.subject)
        cold = type(ref)(str(home), "imported")
        rename_cold = dict(session_id="imported", request_id="cold-rename", expected_revision=0,
                           operation="rename", payload={"title": "owned import"})
        await mutate_session(owner, actor, cold, rename_cold)
        assert db.get_meta(BINDING_PREFIX + "imported") is not None
        foreign = SessionActor("other", str(home), actor.capabilities, "foreign")
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            await mutate_session(owner, foreign, cold, {**rename_cold, "request_id": "foreign"})
        assert db.get_session_title("imported") == "owned import"
        monkeypatch.setattr(owner, "_schedule", lambda ref: None)  # Exercise admission without launching inference.
        submission = Submission("input", ref, {"text": "ask"}, "queue")
        accepted = await owner.submit(actor, submission)
        assert accepted.status == "queued"
        assert await owner.submit(actor, submission) == accepted
        restarted = await initialize_session_authority(runner(), profile_id=str(home), instance_id="second")
        assert restarted.epoch > owner.epoch
        assert ref.session_id in restarted.sessions
        assert create_local_session(restarted, actor, args) == ref
        assert mount_history(restarted, actor, "imported")
        require_history_leaf(restarted, "imported")
        assert db.get_meta(POLICY_PREFIX + ref.session_id) == frozen
        assert db.get_session(ref.session_id)["source"] == "cli"
        assert db.get_session(ref.session_id)["created_source"] == "cli"
        assert not (home / "state.db").exists()
    finally:
        reset_hermes_home_override(token)
