"""Real HTTP adapter and Agent turns with a recording loopback provider."""

import asyncio

import pytest


async def exercise_http_turns(home):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import hermes_yaml as yaml
    from gateway.config import Platform, PlatformConfig
    from gateway.run import GatewayRunner
    from gateway.session_authority import initialize_session_authority
    from gateway.platforms.api_server import APIServerAdapter
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tests.fakes.providers.chat_variants import CText, FakeChatVariantServer
    token = set_hermes_home_override(home)
    adapter = None
    with FakeChatVariantServer([CText('FIRST_NATIVE_REPLY'), CText('SECOND_NATIVE_REPLY')]) as provider:
        config = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8'))
        config.update(model={'provider': 'custom', 'default': 'fake-model', 'base_url': provider.base_url,
            'context_length': 128000}, platform_toolsets={'api_server': ['file']},
            memory={'enabled': False}, compression={'enabled': False})
        (home / 'config.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
        with (home / '.env').open('a', encoding='utf-8') as env:
            env.write('\nOPENAI_API_KEY=sk-local-fixture\n')
        try:
            runner = GatewayRunner()
            owner = await initialize_session_authority(runner, profile_id=str(home), instance_id='model-flow')
            adapter = APIServerAdapter(PlatformConfig(enabled=True))
            adapter.gateway_runner, adapter._session_db, adapter._api_key = runner, owner.db, 'private-key'
            runner.adapters[Platform.API_SERVER] = adapter
            runner._wire_adapter_handlers(adapter)
            app = web.Application()
            app.router.add_post('/api/sessions', adapter._handle_create_session)
            app.router.add_post('/v1/chat/completions', adapter._handle_chat_completions)
            headers = {'Authorization': 'Bearer private-key', 'X-Hermes-Session-Id': 'api-native-model', 'Idempotency-Key': 'one'}
            async with TestClient(TestServer(app)) as client:
                created = await client.post('/api/sessions', json={'id': 'api-native-model'}, headers=headers)
                assert created.status == 201, await created.text()
                first_body = {'model': 'fake-model', 'messages': [{'role': 'user', 'content': 'first user turn'}]}
                first = await asyncio.wait_for(client.post('/v1/chat/completions', json=first_body, headers=headers), 90)
                assert first.status == 200, await first.text()
                first_json = await first.json()
                assert first_json['choices'][0]['message']['content'] == 'FIRST_NATIVE_REPLY'
                retry = await client.post('/v1/chat/completions', json=first_body, headers=headers)
                assert retry.status == 200, await retry.text()
                assert (await retry.json())['choices'][0]['message']['content'] == 'FIRST_NATIVE_REPLY'
                second = await asyncio.wait_for(client.post('/v1/chat/completions', json={'model': 'fake-model',
                    'messages': [{'role': 'user', 'content': 'second user turn'}]}, headers={**headers, 'Idempotency-Key': 'two'}), 90)
                assert second.status == 200, await second.text()
                assert (await second.json())['choices'][0]['message']['content'] == 'SECOND_NATIVE_REPLY'
            rows = owner.db.get_messages_as_conversation('api-native-model')
            assert [row['content'] for row in rows if row['role'] == 'user'] == ['first user turn', 'second user turn']
            assert len(provider.main_requests()) == 2
            prompts = [[m for m in request['messages'] if m['role'] == 'system'] for request in provider.main_requests()]
            assert prompts[0] and prompts[0] == prompts[1]
            assert any(m.get('content') == 'FIRST_NATIVE_REPLY' for m in provider.main_requests()[-1]['messages'])
            assert not (home / 'state.db').exists()
        finally:
            if adapter is not None:
                adapter._response_store.close()
                adapter._run_idempotency_store.close()
            reset_hermes_home_override(token)


@pytest.mark.asyncio
async def test_http_agent_turn_retry_and_continuation_on_native_core(core_pair, native_registry):
    from tests.hermes_db.contracts.test_surface_acquisition import _profile
    db = core_pair[0]
    _profile(db.scope.profile_home, db.scope.store_id)
    await exercise_http_turns(db.scope.profile_home)
