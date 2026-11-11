"""Bot roster, current-history resume and delivery queries use native scope."""

from dataclasses import replace

import pytest

from tests.hermes_db.contracts.test_gateway_authority import _owner_at


@pytest.mark.asyncio
async def test_current_history_resume_keeps_prefix_and_restores_after_owner_restart(core_pair, monkeypatch):
    from gateway.session_local_migration import resolve_local_target
    from gateway.session_listing import stored_picker_sessions
    from hermes_db.domains.runtime.local_access import validate_local_lineage, local_receipt
    from hermes_state_runtime import RuntimeStoreError
    db, other = core_pair
    db.create_session("current", "cli", model="saved")
    db.patch_session_model_config('current', {'reasoning_config': {'enabled': True, 'effort': 'high'},
        'service_tier': 'priority', 'gateway_runtime': {'provider': 'custom', 'base_url': 'http://x.invalid/v1', 'api_mode': 'responses'}})
    db.update_system_prompt("current", "cached\x00prefix")
    db.append_message("current", "user", "retained")
    async with _owner_at(db, monkeypatch, "first") as (owner, actor):
        owner._native_legacy_transports = {actor.transport_id: actor}
        assert "current" in [r['id'] for r in stored_picker_sessions(owner, actor, limit=20)['sessions']]
        with pytest.raises(RuntimeStoreError, match="permission_denied"):
            resolve_local_target(owner, replace(actor, transport_id="remote"), "current")
        ref = resolve_local_target(owner, actor, "current")
        assert ref.session_id == "current"
        receipt = local_receipt(db, "current")
        assert validate_local_lineage(db, receipt) == "current"
        assert receipt['history_session_id'] == "current" and "legacy_session_id" not in receipt
        import json
        request = json.loads(receipt['policy']['request_json'])
        assert request['reasoning'] == 'high' and request['service_tier'] == 'priority'
        assert json.loads(receipt['policy']['config_json'])['model']['api_mode'] == 'responses'
        assert other.get_session("current") is None
    async with _owner_at(db, monkeypatch, "second") as (owner, actor):
        assert resolve_local_target(owner, actor, "current").session_id == "current"
        assert db.get_session("current")['system_prompt'] == "cached\x00prefix"
        assert db.get_messages_as_conversation("current")[0]['content'] == "retained"


@pytest.mark.asyncio
async def test_native_bot_roster_displacement_and_request_lookup_are_store_scoped(core_pair, monkeypatch):
    from gateway.session_bot import _admission_at, _displace_bot_chat
    from gateway.session_group_controls import _read_bot_sessions
    from gateway.session_local import create_local_session
    from hermes_db.domains.runtime.access import runtime_for_store
    db, other = core_pair
    async with _owner_at(db, monkeypatch, "bot-owner") as (owner, actor):
        ref = create_local_session(owner, actor, dict(request_id="bot-create", source="gui", toolsets=[]))
        db.set_session_title(ref.session_id, "Bot Chat")
        db.append_message(ref.session_id, "assistant", "  中文  preview ")
        row = _read_bot_sessions(db, actor.subject, False)
        assert row['canonical_session']['id'] == ref.session_id
        assert row['last_session']['preview'] == '中文 preview'
        assert _read_bot_sessions(other, actor.subject, False)['canonical_session'] is None
        runtime = runtime_for_store(db)
        admitted = runtime.admit_input(epoch=owner.epoch, principal_id=actor.subject, session_id=ref.session_id,
            request_id="bot:key", payload={"text": "hello"})
        assert _admission_at(owner, ref.session_id, "bot:key") == admitted['admission_id']
        assert runtime.has_request("bot:key") and not runtime_for_store(other).has_request("bot:key")
        assert _displace_bot_chat(db, ref.session_id)
        assert not _displace_bot_chat(db, ref.session_id)
        assert db.get_session_title(ref.session_id).startswith('Bot Chat (')
