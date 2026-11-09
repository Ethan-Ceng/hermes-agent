"""Ordinary configured entry points on real PostgreSQL, including a one-connection pool."""

from dataclasses import replace
import json

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.usefixtures('pg_sqlite_guard')]


@pytest.fixture
def surface_config(postgres_test_config, postgres_schema, tmp_path, monkeypatch):
    import hermes_yaml as yaml
    from hermes_db.schema import upgrade_schema
    from hermes_db.access import close_session_resources
    import hermes_state
    # The root isolation fixture pins this constant; exercise call-time profile resolution.
    monkeypatch.setattr(hermes_state, 'DEFAULT_DB_PATH', hermes_state._IMPORT_DEFAULT_DB_PATH)
    settings = replace(postgres_test_config.settings, schema=postgres_schema, pool_size=1,
        max_overflow=0, connection_budget=1, pool_timeout_seconds=2)
    upgrade_schema(settings)
    homes = [tmp_path / 'first', tmp_path / 'second']
    config = {'platform_toolsets': {'cli': []}, 'model': {'provider': 'custom', 'default': 'm',
        'base_url': 'http://provider.invalid/v1'}, 'storage': {'backend': 'postgresql'}}
    options = {key: getattr(settings, key) for key in settings.__dataclass_fields__ if key != 'dsn'}
    for home, store_id in zip(homes, ('surface-one', 'surface-two')):
        home.mkdir()
        config['storage']['postgresql'] = {**options, 'store_id': store_id}
        (home / 'config.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
        (home / '.env').write_text('HERMES_POSTGRES_DSN=' + json.dumps(settings.dsn) + '\n', encoding='utf-8')
    try:
        yield homes
    finally:
        close_session_resources()


def test_configured_factory_and_cli_retain_independent_scope(surface_config):
    from hermes_cli.db_setup import open_profile_db
    from hermes_cli.main_session_storage import read_session_store
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    first, second = surface_config
    for home, text in ((first, 'one'), (second, 'two')):
        with open_profile_db(home) as handle:
            handle.sessions.create_session('same', 'cli')
            handle.sessions.append_message('same', 'user', text)
    token = set_hermes_home_override(first)
    try:
        with read_session_store() as reader:
            assert reader.get_messages_as_conversation('same')[0]['content'] == 'one'
    finally:
        reset_hermes_home_override(token)
    assert all(not (home / 'state.db').exists() for home in surface_config)


@pytest.mark.parametrize('surface', ['agent_recall', 'tui', 'acp'])
def test_agent_tui_and_acp_open_the_configured_scope(surface_config, monkeypatch, surface):
    from hermes_cli.db_setup import open_profile_db
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from acp_adapter.session import SessionManager
    from tui_gateway import server
    from run_agent import AIAgent
    home = surface_config[0]
    with open_profile_db(home) as handle:
        handle.sessions.create_session('retained', 'acp')
        handle.sessions.append_message('retained', 'user', 'prefix')
    agent = object.__new__(AIAgent)
    agent._session_db = None
    monkeypatch.setattr(server, '_db', None)
    monkeypatch.setattr(server, '_launch_state_db_path', lambda: home / 'state.db')
    opens = {'agent_recall': agent._get_session_db_for_recall, 'tui': server._get_db, 'acp': SessionManager()._get_db}
    token = set_hermes_home_override(home)
    try:
        db = opens[surface]()
        assert db.scope.store_id == 'surface-one'
        assert db.get_messages_as_conversation('retained')[0]['content'] == 'prefix'
        db.close()
    finally:
        reset_hermes_home_override(token)


@pytest.mark.asyncio
async def test_gateway_api_responses_and_run_receipts_share_one_connection(surface_config):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.config import PlatformConfig
    from gateway.run import GatewayRunner
    from gateway.session_authority import initialize_session_authority
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.platforms.api_server_response_admissions import _lookup_admission
    from gateway.session_api_turn import admit_api_turn
    from hermes_db.integration.runtime_access import runtime_for_store
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    home = surface_config[0]
    token = set_hermes_home_override(home)
    adapter = None
    try:
        runner = GatewayRunner()
        owner = await initialize_session_authority(runner, profile_id=str(home), instance_id='pg-surface')
        from hermes_db.health import profile_home_for_store
        assert profile_home_for_store(owner.db) == home.resolve()
        from gateway.session_authorities import authority_for_home
        assert authority_for_home(runner, home) is owner
        runner.session_authority = owner
        adapter = APIServerAdapter(PlatformConfig(enabled=True))
        adapter.gateway_runner, adapter._session_db, adapter._api_key = runner, owner.db, 'test-key'
        runner._adapter_for_source = lambda source: adapter
        app = web.Application()
        app.router.add_post('/api/sessions', adapter._handle_create_session)
        async with TestClient(TestServer(app)) as client:
            created = await client.post('/api/sessions', json={'id': 'http-session'},
                headers={'Authorization': 'Bearer test-key'})
            assert created.status == 201, await created.text()
        args = dict(session_id='api-target', request_id='durable-request', user_message='hello', conversation_history=[])
        admitted = admit_api_turn(adapter, **args)[2]
        assert admit_api_turn(adapter, **args)[2]['admission_id'] == admitted['admission_id']
        responses = adapter._response_store
        responses.bind_request_key('response-key', 'fingerprint')
        found = responses.atomically(_lookup_admission, owner, responses, ('response-key', 'fingerprint'), 'durable-request')
        assert found[2]['admission_id'] == admitted['admission_id']
        claim = runtime_for_store(owner.db).claim_input(epoch=owner.epoch, session_id='api-target')
        runtime_for_store(owner.db).settle_input(epoch=owner.epoch, admission_id=admitted['admission_id'],
            generation=claim['generation'], outcome='completed', result={'final_response': 'ok'})
        runs = adapter._run_idempotency_store
        runs.reserve('api-scope', 'client-key', 'digest', 'run-id', {'status': 'queued'})
        runs.update_status('run-id', {'status': 'completed'}, scope='api-scope')
        assert runs.status_for_run('api-scope', 'run-id')['status']['status'] == 'completed'
        assert not (home / 'state.db').exists()
    finally:
        if adapter is not None:
            adapter._response_store.close()
            adapter._run_idempotency_store.close()
        reset_hermes_home_override(token)


@pytest.mark.asyncio
async def test_worker_private_owner_receipts_on_real_postgresql(pg_store, pg_runtime, monkeypatch):
    from tests.hermes_db.contracts.test_worker_owner_wiring import test_owner_reserves_adopts_persists_and_fences_worker_with_child
    await test_owner_reserves_adopts_persists_and_fences_worker_with_child(pg_store, pg_runtime, monkeypatch)


@pytest.mark.asyncio
async def test_hosted_coordination_uses_selected_backend_and_preserves_scope_on_restart(surface_config, monkeypatch):
    import asyncio
    from contextlib import closing
    from types import SimpleNamespace
    from gateway.hosted_rooms import create_room, probe_hosted_room, room_state
    from gateway.session_hosted_service import CanonicalHostedRoomService
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.access import open_session_store
    from hermes_db.integration.runtime_access import runtime_for_store
    from hermes_state_runtime import RuntimeStoreError
    home, other_home = surface_config
    monkeypatch.setattr('gateway.hosted_rooms.local_authority_gateway_id', lambda: 'test')
    with _owning_profile(home), closing(open_session_store(home / 'state.db')) as db:
        runtime = runtime_for_store(db)
        owner = SimpleNamespace(db=db, profile_id=str(home), epoch=runtime.begin_epoch(instance_id='owner'))
        service = CanonicalHostedRoomService(owner, asyncio.get_running_loop())
        assert service.db_path.profile_home == home.resolve() and service.db_path.store_id == 'surface-one'
        service.authorize_room('alice', 'room', create=True)
        create_room(service.db_path, room_id='room', name='Original', authority_gateway_id='test',
            members=[{'member_id': 'default', 'profile': 'default', 'handle': 'bot'}])
        restarted = CanonicalHostedRoomService(owner, asyncio.get_running_loop())
        assert restarted.authorize_room('alice', 'room')
        assert [binding.room_id for binding in restarted.bindings()] == ['room']
        with pytest.raises(RuntimeStoreError, match='permission_denied'):
            restarted.authorize_room('bob', 'room', create=True)
        new_owner = SimpleNamespace(db=db, profile_id=str(home), epoch=runtime.begin_epoch(instance_id='replacement'))
        replacement = CanonicalHostedRoomService(new_owner, asyncio.get_running_loop())
        assert replacement.authorize_room('alice', 'room')
        with pytest.raises(RuntimeStoreError, match='stale_epoch'):
            service.authorize_room('alice', 'room')
        with _owning_profile(other_home), closing(open_session_store(other_home / 'state.db')) as other:
            other_owner = SimpleNamespace(db=other, profile_id=str(other_home), epoch=runtime_for_store(other).begin_epoch(instance_id='other'))
            other_service = CanonicalHostedRoomService(other_owner, asyncio.get_running_loop())
            assert not probe_hosted_room(other_service.db_path, room_id='room')
            other_service.authorize_room('bob', 'room', create=True)
            create_room(other_service.db_path, room_id='room', name='Other', authority_gateway_id='test',
                members=[{'member_id': 'default', 'profile': 'default', 'handle': 'bot'}])
            assert room_state(replacement.db_path, room_id='room')['name'] == 'Original'
        assert not (home / 'state.db').exists() and not (home / 'shared-state.db').exists()


@pytest.mark.asyncio
async def test_current_history_claim_survives_owner_restart(pg_pair, monkeypatch):
    from tests.hermes_db.contracts.test_bot_native_storage import test_current_history_resume_keeps_prefix_and_restores_after_owner_restart
    await test_current_history_resume_keeps_prefix_and_restores_after_owner_restart(pg_pair, monkeypatch)


@pytest.mark.asyncio
async def test_webhook_startup_queries_and_terminal_fences_use_real_postgresql(pg_pair, monkeypatch):
    from tests.hermes_db.contracts.test_gateway_authority import _owner_at
    from tests.hermes_db.contracts.test_native_startup_webhook import test_native_webhook_delivery_queries_and_finalization_do_not_cross_stores
    async with _owner_at(pg_pair[0], monkeypatch, 'webhook-owner') as (owner, _actor):
        test_native_webhook_delivery_queries_and_finalization_do_not_cross_stores((owner, *pg_pair))


@pytest.mark.asyncio
async def test_http_agent_retry_and_continuation_with_single_pg_connection(surface_config):
    from tests.hermes_db.contracts.test_native_http_turn import exercise_http_turns
    await exercise_http_turns(surface_config[0])
