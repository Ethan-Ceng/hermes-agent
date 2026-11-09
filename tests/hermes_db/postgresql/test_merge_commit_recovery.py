"""Real COMMIT followed by lost acknowledgement must replay without losing fences."""

from contextlib import closing
import time
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def lose_one_commit_ack(monkeypatch, engine):
    import psycopg
    original = engine.dialect.do_commit
    fired = []
    def committed_but_unacknowledged(connection):
        original(connection)
        if not fired:
            fired.append(True)
            raise psycopg.OperationalError('simulated lost COMMIT acknowledgement')
    monkeypatch.setattr(engine.dialect, 'do_commit', committed_but_unacknowledged)
    return fired


def test_closed_admission_replays_after_real_commit_ack_loss(pg_profiles, monkeypatch):
    from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
    from hermes_db.access import open_session_store
    from hermes_db.errors import UnknownCommitError
    from hermes_db.integration.run_resources import ProfileRunStores
    with pg_profiles('one') as home, closing(open_session_store(home / 'state.db')) as db:
        resources = ProfileRunStores(RunIdempotencyStore)
        try:
            with monkeypatch.context() as patch:
                fired = lose_one_commit_ack(patch, db._transactions.engine)
                with pytest.raises(UnknownCommitError):
                    resources.find_or_close('scope', 'closed')
                assert fired
        finally:
            resources.close()
        reopened = ProfileRunStores(RunIdempotencyStore)
        try:
            assert reopened.find_or_close('scope', 'closed') == ('closed', None)
            assert reopened.reserve('scope', 'closed', 'late', 'late-run', {'status': 'running'})[0] == 'conflict'
        finally:
            reopened.close()


def test_grant_replacement_replay_keeps_exact_long_grant_once(pg_profiles, monkeypatch):
    from gateway import hosted_rooms as rooms
    from hermes_db.access import open_session_store
    from hermes_db.errors import UnknownCommitError
    now = time.time()
    expiries = {'long': now + 1000, 'short': now + 100}
    record = dict(room_id='room', member_id='ops', target_url='http://127.0.0.1:9121', target_profile='ops',
        grant='long', catalog_json='{}', cancellation_scope_id='cancel', trace_id='trace',
        transport_security='loopback', status='ready', updated_at=now)
    with pg_profiles('one') as home, closing(open_session_store(home / 'state.db')) as db:
        location = rooms.default_db_path()
        rooms.upsert_room_link_record(location, record=record, max_links=8, expiry=expiries.__getitem__)
        replacement = {**record, 'grant': 'short'}
        with monkeypatch.context() as patch:
            fired = lose_one_commit_ack(patch, db._transactions.engine)
            with pytest.raises(UnknownCommitError):
                rooms.upsert_room_link_record(location, record=replacement, max_links=8, expiry=expiries.__getitem__)
            assert fired
        rooms.upsert_room_link_record(location, record=replacement, max_links=8, expiry=expiries.__getitem__)
        assert rooms.held_room_grant_revokes(location, room_id='room', now=now) == [
            {'target_url': record['target_url'], 'grant': 'long'}]
        assert rooms.list_room_link_records(location)[0]['grant'] == 'short'
