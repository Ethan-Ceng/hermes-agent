"""Dashboard browsing and offline metadata mutations select the native store."""

from hermes_cli.db_sessions import _build_session_resources

import pytest


def test_native_browse_timeline_and_offline_import_have_no_local_database(core_pair, native_registry, monkeypatch):
    pytest.importorskip('fastapi')
    from gateway.session_contract import SessionActor
    from hermes_cli import web_server_sessions as web
    from hermes_cli.web_routers.sessions import _timeline_session_id
    from hermes_cli import db_sessions as factory
    from hermes_db.domains.runtime.access import runtime_for_store
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from tests.hermes_db.contracts.test_surface_acquisition import _profile
    db, other = core_pair
    registry, _ = native_registry
    home = db.scope.profile_home
    _profile(home, db.scope.store_id)
    monkeypatch.setattr(factory, 'acquire_db', lambda settings, scope: registry.acquire(settings.postgresql, scope, build=_build_session_resources))
    monkeypatch.setattr(web, '_session_db_path_for_profile', lambda profile: home / 'state.db')
    token = set_hermes_home_override(home)
    try:
        db.create_session('native', 'cli')
        db.append_message('native', 'user', 'retained')
        with web._open_session_db_at_path(home / 'state.db', read_only=True) as opened:
            assert _timeline_session_id(opened, 'native', opened._own_profile) == 'native'
            assert not opened.session_is_empty('native')
        actor = SessionActor('reader', str(home), frozenset({'session:read', 'session:create', 'session:control'}), 'http')
        epoch = runtime_for_store(db).begin_epoch(instance_id='existing-owner')
        current = db.get_session('native')
        result = web._mutate_offline_store(None, actor, dict(operation='rename', session_id='native',
            request_id='rename', expected_revision=current['runtime_revision'], payload={'title': '中文'}))
        assert result['operation'] == 'rename' and db.get_session_title('native') == '中文'
        assert runtime_for_store(db).current_epoch() == epoch
        payload = [dict(id='imported', source='cli', messages=[dict(role='user', content='imported text')])]
        web._mutate_offline_store(None, actor, dict(operation='import', session_id='imported', request_id='import',
            expected_revision=0, payload={'sessions': payload}))
        assert runtime_for_store(db).authorize_history(actor, 'imported', native_transport=False)
        assert other.get_session('imported') is None
        assert not (home / 'state.db').exists()
    finally:
        reset_hermes_home_override(token)


def test_dashboard_maps_unknown_commit_without_sdk_retry():
    pytest.importorskip('fastapi')
    from fastapi import HTTPException
    from hermes_cli.web_routers._common import http_failure
    from hermes_db.errors import UnknownCommitError
    with pytest.raises(HTTPException) as raised:
        with http_failure('test', 500):
            raise UnknownCommitError('unknown')
    assert raised.value.status_code == 503
    assert raised.value.headers['x-should-retry'] == 'false'


def test_acp_catalog_from_existing_native_handle_uses_the_owning_scope(core_pair, monkeypatch):
    from acp_adapter.session import SessionManager
    from acp_adapter import catalog
    db = core_pair[0]
    seen = []
    monkeypatch.setattr(catalog, 'read_catalog_rows', lambda path: seen.append(path) or {})
    assert SessionManager(db=db)._catalog_rows() == {}
    assert seen == [db.scope.profile_home / 'state.db']


def test_acp_failed_native_read_never_restores_empty_history(core_pair, monkeypatch):
    from acp_adapter.session import SessionManager
    from hermes_db.errors import StorageUnavailableError
    db = core_pair[0]
    manager = SessionManager(db=db)
    db.create_session('editor', 'acp')
    def unavailable(*args, **kwargs):
        raise StorageUnavailableError('storage unavailable')
    monkeypatch.setattr(db, 'get_messages_as_conversation', unavailable)
    with pytest.raises(StorageUnavailableError):
        manager._restore('editor')
    assert not manager._sessions


def test_repo_root_discovery_preserves_recorded_roots_and_other_stores(core_pair):
    db, other = core_pair
    for store in (db, other):
        store.create_session('missing', 'cli', cwd='/work/sub')
        store.create_session('recorded', 'cli', cwd='/work/sub', git_repo_root='/kept')
    db.backfill_repo_roots({'/work/sub': '/work'})
    assert db.get_session('missing')['git_repo_root'] == '/work'
    assert db.get_session('recorded')['git_repo_root'] == '/kept'
    assert other.get_session('missing')['git_repo_root'] is None
