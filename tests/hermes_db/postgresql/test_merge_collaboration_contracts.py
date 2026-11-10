"""Incoming collaboration operations persist and recover with SQLite forbidden."""

from contextlib import closing
import time
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_merge_migration_head_is_ready(postgres_test_config, postgres_schema):
    from dataclasses import replace
    from hermes_db.schema import upgrade_schema
    from hermes_db.errors import StorageUnavailableError
    try:
        status = upgrade_schema(replace(postgres_test_config.settings, schema=postgres_schema))
    except StorageUnavailableError as exc:
        original = getattr(exc.__context__, 'orig', None)
        diagnostic = getattr(original, 'diag', None)
        pytest.fail(f"migration failed: {getattr(original, 'sqlstate', None)} {getattr(diagnostic, 'message_primary', None)}")
    assert status['full_system_ready']


def test_revoke_debts_hold_long_grants_and_survive_room_retirement(pg_profiles):
    from gateway import hosted_rooms as rooms
    from tests.hermes_db.postgresql.test_room_policy import create
    now = time.time()
    expiries = {'long': now + 1000, 'short': now + 100}
    record = dict(room_id='room', member_id='ops', target_url='http://127.0.0.1:9121', target_profile='ops',
        grant='long', catalog_json='{}', cancellation_scope_id='cancel', trace_id='trace',
        transport_security='loopback', status='ready', updated_at=now)
    with pg_profiles('one'):
        location = rooms.default_db_path()
        create(location)
        rooms.upsert_room_link_record(location, record=record, max_links=8, expiry=expiries.__getitem__)
        rooms.upsert_room_link_record(location, record={**record, 'grant': 'short'}, max_links=8, expiry=expiries.__getitem__)
        assert rooms.held_room_grant_revokes(location, room_id='room', now=now) == [
            {'target_url': record['target_url'], 'grant': 'long'}]
        assert rooms.due_room_grant_revokes(location, limit=8, now=now) == []
        with pytest.raises(rooms.RoomHeldGrantsPendingError):
            rooms.disband_room(location, room_id='room', expected_gateway_id='owner', expected_epoch=1, now=now)
        assert rooms.retire_room_link_records(location, room_id='room', expiry=expiries.__getitem__, now=now) == 1
        rooms.disband_room(location, room_id='room', expected_gateway_id='owner', expected_epoch=1, now=now)
    with pg_profiles('one'):
        location = rooms.default_db_path()
        due = rooms.due_room_grant_revokes(location, limit=8, now=now)
        assert {row['grant'] for row in due} == {'long', 'short'}
        assert rooms.room_has_peer_obligations(location, room_id='room', now=now)
        for row in due:
            rooms.settle_room_grant_revoke(location, room_id='room', member_id='ops',
                grant_digest=row['grant_digest'], retry_at=now + 10)
        assert rooms.due_room_grant_revokes(location, limit=8, now=now) == []
        assert all(row['attempts'] == 1 for row in rooms.due_room_grant_revokes(location, limit=8, now=now + 11))
    with pg_profiles('two'):
        assert not rooms.owes_room_grant_revokes(rooms.default_db_path())


def test_attempt_home_is_first_writer_owned_and_disband_clears_evidence(pg_profiles):
    from gateway import hosted_rooms as rooms, hosted_room_driver as driver
    from gateway import session_hosted_member_homes as homes
    from hermes_cli.db_sessions import open_session_store
    from tests.gateway.test_hosted_room_driver import FakeClock, _admit, _identity, _lease
    with pg_profiles('one') as home, closing(open_session_store(home / 'state.db')) as db:
        location = rooms.default_db_path()
        rooms.create_room(location, room_id='room-1', name='Room', members=[{'profile': 'ops', 'handle': 'ops'}],
                          authority_gateway_id='gateway-a', now=90)
        clock = FakeClock()
        lease, identity = _lease(location, clock, ttl=60), _identity()
        _admit(location, identity, clock)
        attempt = driver.start_task(location, identity, lease, expected_cancel_generation=0, clock=clock)
        homes.record_member_home(db, 'room-1', 'ops', home / 'old')
        homes.record_attempt_home(db, 'room-1', 'ops', identity.task_id, attempt.execution_generation, home / 'old')
        homes.record_attempt_home(db, 'room-1', 'ops', identity.task_id, attempt.execution_generation, home / 'new')
        probe = {'status': 'stopping', 'identity': identity, 'execution_generation': attempt.execution_generation}
        assert homes.stopping_attempt_home(db, 'room-1', 'ops', probe) == home / 'old'
        assert homes._recorded_homes(db, 'room-1', 'ops') == [home / 'old']
    with pg_profiles('one') as home, closing(open_session_store(home / 'state.db')) as db:
        assert homes.stopping_attempt_home(db, 'room-1', 'ops', probe) == home / 'old'
        rooms.disband_room(rooms.default_db_path(), room_id='room-1', expected_gateway_id='gateway-a', expected_epoch=1)
        assert homes._recorded_homes(db, 'room-1', 'ops') == []
        assert homes.stopping_attempt_home(db, 'room-1', 'ops', probe) is None


def test_old_activity_and_continue_cannot_take_new_discussion(pg_profiles):
    from gateway import hosted_rooms as rooms
    from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
    from tests.hermes_db.postgresql.test_room_policy import create, append
    with pg_profiles('one'):
        location = rooms.default_db_path()
        create(location)
        append(location, 'old', 'message.user', {'text': 'old', 'thread_id': 'same'})
        append(location, 'new', 'message.user', {'text': 'new', 'thread_id': 'same'})
        append(location, 'old-done', 'room.activity', {'thread_id': 'same', 'discussion_event_id': 'old', 'status': 'settled'})
        last = append(location, 'old-continue', 'room.continued', {'thread_id': 'same', 'discussion_event_id': 'old', 'grant': 1})
        state = HostedRoomPolicyCheckpoint(location).snapshot(room_id='room', latest_seq=last['seq'])
        assert 'new' in {event['event_id'] for event in state.events}
        from hermes_cli.db_domains import acquire_profile_domain
        from hermes_db.tables.room_policy import threads, transcript_state
        from sqlalchemy import select
        with acquire_profile_domain('rooms') as store, store.read() as conn:
            assert conn.scalar(select(threads.c.discussion_event_id).where(threads.c.store_id == 'one')) == b'new'
        with acquire_profile_domain('rooms') as store, store.write() as conn:
            conn.execute(transcript_state.update().where(transcript_state.c.store_id == 'one').values(schema_version=4))
            conn.execute(threads.update().where(threads.c.store_id == 'one').values(discussion_event_id=b'old'))
        assert HostedRoomPolicyCheckpoint(location).snapshot(room_id='room', latest_seq=last['seq']) == state


def test_closed_admission_persists_and_races_reserve_in_own_scope(pg_pair):
    from concurrent.futures import ThreadPoolExecutor
    from hermes_db.domains.runtime.postgres.idempotency import PostgresRunIdempotencyStore
    owner, peer = map(PostgresRunIdempotencyStore, pg_pair)
    assert owner.find_or_close('scope', 'closed') == ('closed', None)
    assert owner.find_or_close('scope', 'closed') == ('closed', None)
    assert owner.reserve('scope', 'closed', 'body', 'run', {'status': 'running'})[0] == 'conflict'
    assert peer.reserve('scope', 'closed', 'body', 'run', {'status': 'running'})[0] == 'created'
    assert owner.reserve('other', 'closed', 'body', 'run2', {'status': 'running'})[0] == 'created'
    with ThreadPoolExecutor(max_workers=2) as pool:
        closing_key = pool.submit(owner.find_or_close, 'scope', 'race')
        admission = pool.submit(owner.reserve, 'scope', 'race', 'body', 'racing-run', {'status': 'running'})
        closed, reserved = closing_key.result(), admission.result()
    assert (closed[0], reserved[0]) in {('closed', 'conflict'), ('found', 'created')}
    reopened = PostgresRunIdempotencyStore(pg_pair[0])
    assert reopened.find_or_close('scope', 'race')[0] == closed[0]


def test_retarget_notify_keeps_cursor_and_existing_owner_wins(pg_profiles):
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_notify as notify
    with pg_profiles('one'), kbc.connect_closing() as store:
        task = kb.create_task(store, title='completion')
        for chat in ('child', 'owner'):
            notify.add_notify_sub(store, task_id=task, platform='tui', chat_id=chat)
        notify.advance_notify_cursor(store, task_id=task, platform='tui', chat_id='owner', new_cursor=42)
        assert notify.retarget_notify_subs(store, platform='TUI', from_chat_ids=['child'], to_chat_id='owner') == 0
        rows = notify.list_notify_subs(store)
        assert len(rows) == 1 and rows[0]['chat_id'] == 'owner' and rows[0]['last_event_id'] == 42
        notify.add_notify_sub(store, task_id=task, platform='tui', chat_id='other-child')
        notify.advance_notify_cursor(store, task_id=task, platform='tui', chat_id='other-child', new_cursor=17)
        assert notify.retarget_notify_subs(store, platform='tui', from_chat_ids=['other-child'], to_chat_id='new-owner') == 1
    with pg_profiles('one'), kbc.connect_closing() as store:
        assert {row['chat_id']: row['last_event_id'] for row in notify.list_notify_subs(store)} == {'owner': 42, 'new-owner': 17}


def test_remote_receipt_removal_is_exact_run_cas_and_store_scoped(pg_profiles):
    from gateway import hosted_rooms as rooms
    from tests.hermes_db.postgresql.test_room_policy import create
    record = dict(room_id='room', home_install_id='home', authority_gateway_id='owner', authority_epoch=1,
        member_id='ops', target_install_id='target', target_profile='ops', task_id='task', execution_generation=1,
        run_id='run', session_id='session')
    for profile in ('one', 'two'):
        with pg_profiles(profile):
            location = rooms.default_db_path()
            create(location)
            rooms.upsert_remote_run_receipt(location, record=record)
    with pg_profiles('one'):
        location = rooms.default_db_path()
        assert not rooms.drop_remote_run_receipt(location, record=record, run_id='stale-run')
        assert rooms.remote_run_receipt(location, record=record)['run_id'] == 'run'
        assert rooms.drop_remote_run_receipt(location, record=record, run_id='run')
        assert not rooms.drop_remote_run_receipt(location, record=record, run_id='run')
    with pg_profiles('two'):
        assert rooms.remote_run_receipt(rooms.default_db_path(), record=record)['run_id'] == 'run'


@pytest.mark.parametrize('expiry', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_grant_horizon_is_retained_but_expires_within_bound(pg_profiles, expiry):
    import base64
    import json
    import math
    from gateway import hosted_rooms as rooms
    from gateway.hosted_room_peer import room_grant_hard_expiry, MAX_STATUS_GRANT_TTL_SECONDS
    from tests.hermes_db.postgresql.test_room_policy import create
    now = 100.0
    payload = json.dumps({'expires_at': 101, 'status_expires_at': str(expiry)}).encode('ascii')
    token = base64.urlsafe_b64encode(payload).decode('ascii').rstrip('=') + '.eA'
    parsed = room_grant_hard_expiry(token, now=now)
    with pg_profiles('one'):
        location = rooms.default_db_path()
        create(location)
        rooms.hold_room_grant_revoke(location, room_id='room', member_id='ops', target_url='http://127.0.0.1:9121',
                                     grant=token, expires_at=expiry, now=now)
        assert rooms.held_room_grant_revokes(location, room_id='room', now=now)
        assert rooms.held_room_grant_revokes(location, room_id='room', now=now + rooms.MAX_OWED_REVOKE_SECONDS + 1) == []
        assert not rooms.owes_room_grant_revokes(location)
    assert math.isfinite(parsed) and parsed == now + MAX_STATUS_GRANT_TTL_SECONDS
