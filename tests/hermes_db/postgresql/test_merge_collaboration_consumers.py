"""New Discard HTTP and notification-poller consumers use the selected PG store."""

import asyncio
from contextlib import closing, ExitStack
import time
from types import SimpleNamespace
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_poller_reclaims_child_subscription_and_keeps_delivery_cursor(pg_profiles):
    from hermes_db.access import open_session_store
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_notify as notify
    from tui_gateway import server
    with pg_profiles('one') as home, closing(open_session_store(home / 'state.db')) as db:
        db.create_session('parent', 'cli')
        db.create_session('child', 'subagent', parent_session_id='parent', model_config={'_delegate_from': 'parent'})
        with kbc.connect_closing() as board:
            task = kb.create_task(board, title='finish this card')
            notify.add_notify_sub(board, task_id=task, platform='tui', chat_id='child')
            kb.complete_task(board, task, summary='completed work')
        session = {'session_key': 'parent', 'profile_home': str(home)}
        messages = server._collect_kanban_notifications(session)
        assert len(messages) == 1 and 'finish this card' in str(messages[0])
        with kbc.connect_closing() as board:
            row, = notify.list_notify_subs(board)
            assert row['chat_id'] == 'parent' and row['last_event_id'] > 0
    with pg_profiles('one'):
        assert server._collect_kanban_notifications(session) == []
    with pg_profiles('two') as other:
        assert server._collect_kanban_notifications({'session_key': 'parent', 'profile_home': str(other)}) == []


@pytest.mark.asyncio
async def test_discard_closes_real_http_admission_and_blocks_delayed_post_after_reopen(pg_profiles, monkeypatch):
    from gateway import hosted_room_driver as driver
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms import api_server_runs
    from gateway.platforms.api_server import APIServerAdapter
    from gateway.platforms.api_server_storage_resources import drain_response_stores
    from gateway.session_controls import AuthorityConnection
    from gateway.run import GatewayRunner
    from gateway.session_authority import initialize_session_authority
    from gateway.session_group_peers import room_link
    from gateway.session_hosted_service import CanonicalHostedRoomService
    from hermes_db.access import open_session_store
    from hermes_db.integration.run_resources import ProfileRunStores
    from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
    from tests.gateway import test_session_group_peers as peers
    from tui_gateway.hosted_room_peer_http import PeerRunsHTTPError
    from tui_gateway.hosted_room_peer_transport import build_member_dispatch

    async def inert(*args, **kwargs):
        pass
    monkeypatch.setattr(api_server_runs, '_execute_run', inert)
    import hermes_state
    # The root test fixture pins the native default; exercise runtime Profile selection here.
    monkeypatch.setattr(hermes_state, 'DEFAULT_DB_PATH', hermes_state._IMPORT_DEFAULT_DB_PATH)
    with pg_profiles('one') as home, closing(open_session_store(home / 'state.db')) as db, ExitStack() as resources:
        adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={'key': 'test-target-api-key'}))
        def close_resources():
            adapter._run_idempotency_store.close()
            for resource in drain_response_stores(adapter):
                resource.close()
        resources.callback(close_resources)
        runner = GatewayRunner()
        resources.callback(runner.close_all_session_db_handles)
        resources.callback(runner.session_store.close_all_db_handles)
        authority = await initialize_session_authority(runner, profile_id=str(home), instance_id='owner', db=db)
        from gateway.session_cron import unbind_owner
        resources.callback(unbind_owner, authority)
        runner.adapters = {Platform.API_SERVER: adapter}
        adapter.gateway_runner, adapter._session_db = runner, db
        service = authority.hosted_room_service = CanonicalHostedRoomService(authority, None)
        service.runtime.status = lambda: {'running': True, 'stopping': False}
        gateway = SimpleNamespace(home=home, db=db, adapter=adapter, authority=authority, service=service,
            owner=AuthorityConnection(authority, object(), {'user_id': 'owner'}, operator=True))
        http, url = await peers.serve(gateway, monkeypatch, stop=True)
        try:
            catalog = room_link(authority)['catalog']
            room = await peers.linked_room(gateway, catalog)
            grant = (await peers.invite(gateway, room))['grant']
            registration = await gateway.owner.dispatch({'id': 1, 'method': 'groups.peer.register', 'params': {
                'room_id': 'linked', 'member_id': 'reviewer', 'target_url': url, 'target_profile': 'default',
                'grant': grant, 'catalog': catalog}})
            assert 'result' in registration, registration.get('error')
            registered = registration['result']
            assert registered['registered']
            assert (await peers.call(gateway.owner, 'groups.send', room_id='linked', event_id='ask',
                payload={'text': '@reviewer review this', 'thread_id': 'thread'}))['accepted']
            location = service.db_path
            task, = driver.list_tasks(location, room_id='linked', status='queued')
            identity, binding = task['identity'], service.bindings()[0]
            earlier = lambda: time.time() - 30
            crashed = driver.acquire_lease(location, room_id='linked', gateway_id=binding.gateway_id,
                authority_epoch=binding.authority_epoch, process_generation='crashed', ttl_seconds=1, clock=earlier)
            driver.start_task(location, identity, crashed, expected_cancel_generation=0, clock=earlier)
            service = authority.hosted_room_service = CanonicalHostedRoomService(authority, None)
            service.runtime.status = lambda: {'running': True, 'stopping': False}
            lease = service.runtime._ensure_lease(binding)
            driver.recover_room(location, lease, clock=time.time)
            service.runtime._fenced(driver.defer_indeterminate_task, None, driver.get_task(location, identity), lease,
                                    reason='member_unavailable')
            discarded = await peers.call(gateway.owner, 'groups.discard', room_id='linked', member_id='reviewer',
                task_id=identity.task_id, execution_generation=1)
            assert discarded['discarded'] and driver.get_task(location, identity)['status'] == 'cancelled'
            assert adapter._run_statuses == {}
            route, client = service.peer_routes[('linked', 'reviewer')], service.peer_clients[('linked', 'reviewer')]
            delayed = build_member_dispatch(binding=service.bindings()[0], route=route, room_id='linked', task_id=identity.task_id,
                target_profile='default', execution_generation=1, source_event_seq=task['payload']['source_event_seq'],
                prompt=task['payload']['prompt'], trace_id=route.trace_id)
            adapter._run_idempotency_store.close()
            adapter._run_idempotency_store = ProfileRunStores(RunIdempotencyStore)
            with pytest.raises(PeerRunsHTTPError) as refused:
                await asyncio.to_thread(client.dispatch, grant=route.grant, dispatch=delayed.as_mapping())
            assert refused.value.error_code == 'idempotency_key_conflict'
            assert adapter._run_statuses == {}
            # A grant handed in after Disband is a persistent debt, paid by the real supervisor.
            from gateway import hosted_rooms as rooms
            assert 'tombstone' in await peers.call(gateway.owner, 'groups.disband', room_id='linked')
            late = await gateway.owner.dispatch({'id': 2, 'method': 'groups.peer.register', 'params': {
                'room_id': 'linked', 'member_id': 'reviewer', 'target_url': url, 'target_profile': 'default',
                'grant': grant, 'catalog': catalog}})
            assert 'error' in late and rooms.owes_room_grant_revokes(location)
            service.start()
            try:
                deadline = time.monotonic() + 10
                while rooms.owes_room_grant_revokes(location) and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
                assert not rooms.owes_room_grant_revokes(location)
            finally:
                assert await asyncio.to_thread(service.stop, timeout=5)
        finally:
            await http.close()
