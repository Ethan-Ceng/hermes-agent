"""Owner acquisition rejects Workers before configuration and captures both Profiles."""

from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.mark.parametrize('entrypoint', ['open_profile_db', 'open_profile_sessions'])
def test_worker_is_refused_before_profile_configuration(entrypoint, tmp_path, monkeypatch):
    from agent import runtime_session_store
    from hermes_cli import db_setup

    monkeypatch.setattr(runtime_session_store, 'is_worker_process', lambda: True)
    def configuration_must_not_be_read(*_args, **_kwargs):
        pytest.fail('Worker attempted owner configuration before being refused')
    monkeypatch.setattr(db_setup, 'resolve_db_configuration', configuration_must_not_be_read)
    with pytest.raises(runtime_session_store.WorkerPersistenceError, match='owner_store_access_from_worker'):
        getattr(db_setup, entrypoint)(tmp_path)


def test_two_profiles_thread_hops_and_peer_close_use_their_actual_native_datasets(tmp_path):
    from hermes_cli.db_setup import open_profile_db
    from hermes_db.errors import StorageClosedError
    from hermes_state import SessionDB

    homes = [tmp_path / 'one', tmp_path / 'two']
    for home in homes:
        home.mkdir()
        with SessionDB(home / 'state.db'):
            pass  # Explicit creation before ordinary application acquisitions.
    first, peer, second = [open_profile_db(home) for home in (homes[0], homes[0], homes[1])]
    try:
        with ThreadPoolExecutor(max_workers=1) as threads:
            threads.submit(first.sessions.create_session, 'one-row', source='test').result()
            threads.submit(second.sessions.create_session, 'two-row', source='test').result()
        first.close()
        with pytest.raises(StorageClosedError):
            first.sessions
        peer.sessions.append_message('one-row', 'user', 'peer still owns the dataset')
        assert peer.sessions.get_session('two-row') is None
        assert second.sessions.get_session('one-row') is None
        assert peer.sessions.get_messages('one-row')[0]['content'] == 'peer still owns the dataset'
        assert first.scope.profile_home == homes[0].resolve()
        assert second.scope.profile_home == homes[1].resolve()
    finally:
        first.close()
        peer.close()
        second.close()
