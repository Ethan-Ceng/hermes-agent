"""Independent follow-up probes for frozen deletion and mixed-backend routing."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest



@pytest.mark.parametrize('matches', [False, True])
def test_live_handler_checks_held_routing_store_before_effects(monkeypatch, matches):
    from gateway.run_profile_reconcile import purge_profile_identity_verb
    from hermes_db import health
    writes = []
    database = SimpleNamespace(purge_profile_state=lambda name: writes.append(('db', name)) or {})
    store = SimpleNamespace(_routing_db=database,
        purge_profile_routing=lambda name: writes.append(('routing', name)) or 1)
    monkeypatch.setattr(health, 'storage_identity', lambda db: ('postgresql', 'held-target', 'held-store'))
    expected = ['postgresql', 'held-target' if matches else 'other-target', 'held-store']
    reply = purge_profile_identity_verb(SimpleNamespace(session_store=store))(
        {'name': 'gone', 'expected_identity': expected})
    assert reply['ok'] is matches, reply
    assert bool(writes) is matches, writes
    if matches:
        assert reply['storage_identity'] == expected


def test_legacy_handler_is_refused_before_any_mutation(tmp_path, monkeypatch):
    from gateway import control_socket
    from hermes_cli import profiles_deletion_storage as deletion
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings
    root = deletion.SelectedStore(DatabaseSettings(), DatabaseScope(tmp_path), tmp_path / 'state.db')
    plan = deletion.ProfileDeletion(root, root)
    monkeypatch.setattr(deletion.ProfileDeletion, 'verify', lambda self: None)
    writes = []
    def old_handler(home, verb, *, params, timeout):
        if verb == 'purge-profile-identity':
            # The shipped old handler consumes only name and ignores new params.
            writes.append(params['name'])
            return {'ok': True, 'dropped': 1, 'db': {'routing': {'gateway_routing': 1}}}
        return {'ok': False, 'error': 'unknown verb'}
    monkeypatch.setattr(control_socket, 'query_gateway_control', old_handler)
    assert plan.purge_identity('gone', True) is False
    assert writes == [], 'the old server already mutated its unverified dataset before client rejected its reply'


def test_sqlite_deletion_plan_does_not_import_optional_pg_dependencies(tmp_path):
    code = r'''
import importlib.abc, pathlib, sys
class NoPG(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'sqlalchemy','psycopg','alembic'}:
   raise AssertionError('SQLite deletion imported optional PG dependencies')
sys.meta_path.insert(0, NoPG())
from hermes_cli.config import atomic_config_write
from hermes_cli.profiles_deletion_storage import capture, ProfileDeletion
from hermes_cli.db_setup import _owning_profile
from hermes_cli.db_sessions import open_session_store
root=pathlib.Path(sys.argv[1]); target=root/'target'; target.mkdir()
for home in (root,target): atomic_config_write(home/'config.yaml',{'storage':{'backend':'sqlite'}})
from hermes_cli.db_session_schema import initialize_new_profile_sessions
initialize_new_profile_sessions(root)
with _owning_profile(root):
 db=open_session_store(root/'state.db')
 db.create_session('history','cli',session_key='agent:gone:cli:chat',profile_name='gone')
 db.save_gateway_routing_entry('agent:gone:cli:chat','{}')
 db.close()
plan=ProfileDeletion(capture(target),capture(root))
assert plan.purge_identity('gone',False)
plan.purge()
with _owning_profile(root):
 db=open_session_store(root/'state.db')
 assert db.get_session('history') is not None
 assert not db.load_gateway_routing_entries()
 db.close()
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], capture_output=True, text=True,
                            check=False, timeout=40)
    assert result.returncode == 0, result.stderr


@pytest.mark.integration
@pytest.mark.allow_network
def test_pg_source_to_sqlite_room_target_uses_only_selected_target(postgres_test_config, postgres_schema, tmp_path, monkeypatch):
    from cron.scheduler_delivery_room import deliver_to_room
    from gateway import hosted_rooms as rooms
    from hermes_cli import profiles
    from hermes_cli.config import atomic_config_write
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_sessions import open_session_store
    from hermes_db.schema import upgrade_schema
    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(pg)
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    atomic_config_write(source / 'config.yaml', {'storage': {'backend': 'postgresql', 'postgresql': {
        'schema': pg.schema, 'store_id': 'source', 'pool_size': 2, 'max_overflow': 0, 'connection_budget': 2}}})
    (source / '.env').write_text('HERMES_POSTGRES_DSN=' + json.dumps(pg.dsn) + '\n')
    atomic_config_write(target / 'config.yaml', {'storage': {'backend': 'sqlite'}})
    from hermes_cli.db_session_schema import initialize_new_profile_sessions
    initialize_new_profile_sessions(target)
    monkeypatch.setattr(rooms, 'local_authority_gateway_id', lambda: 'review-gateway')
    references = []
    for home in (source, target):
        with _owning_profile(home):
            reference = rooms.default_db_path() if home == source else home / 'state.db'
            rooms.create_room(reference, room_id='same-room', name=home.name, members=[],
                              authority_gateway_id='review-gateway')
            db = open_session_store(home / 'state.db')
            db.set_meta('gateway.hosted.owner.v1:same-room', 'owner')
            db.close()
            references.append(reference)
    monkeypatch.setattr(profiles, 'profile_exists', lambda name: name == 'target')
    monkeypatch.setattr(profiles, 'get_profile_dir', lambda name: target)
    with _owning_profile(source):
        assert deliver_to_room({'id': 'job', 'execution_id': 'mixed'}, 'target only', 'same-room@target') is None
        assert rooms.read_events(references[0], room_id='same-room')['events'] == []
    with _owning_profile(target):
        events = rooms.read_events(references[1], room_id='same-room')['events']
        assert len(events) == 1 and events[0]['payload']['text'] == 'target only'


@pytest.fixture
def deletion_stores(postgres_test_config, postgres_schema, tmp_path):
    from hermes_cli.config import atomic_config_write
    from hermes_cli.profiles_deletion_storage import capture
    from hermes_db.schema import upgrade_schema
    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(pg)
    selected = []
    for name in ('root', 'target', 'peer'):
        home = tmp_path / name
        home.mkdir()
        atomic_config_write(home / 'config.yaml', {'storage': {'backend': 'postgresql', 'postgresql': {
            'schema': pg.schema, 'store_id': name, 'pool_size': 2, 'max_overflow': 0, 'connection_budget': 2}}})
        (home / '.env').write_text('HERMES_POSTGRES_DSN=' + json.dumps(pg.dsn) + '\n')
        store = capture(home)
        with store.open() as handle:
            handle.sessions.create_session('same', 'cli')
            handle.sessions.save_gateway_routing_entry('agent:before:cli:room', '{}')
        selected.append(store)
    return selected


def retarget(selected, store_id):
    from hermes_cli.config_backend import write_config_key
    write_config_key(selected.scope.profile_home / 'config.yaml', 'storage.postgresql.store_id', store_id)


@pytest.mark.integration
@pytest.mark.allow_network
@pytest.mark.parametrize('changed', ['root', 'target'])
def test_confirmed_root_or_target_retarget_refuses_before_identity_effects(deletion_stores, changed):
    from hermes_cli.profiles_deletion_storage import ProfileDeletion
    from hermes_db.errors import StorageConfigurationError
    root, target, _peer = deletion_stores
    plan = ProfileDeletion(target, root)
    retarget(root if changed == 'root' else target, 'peer')
    with pytest.raises(StorageConfigurationError, match='identity changed'):
        plan.purge_identity('before', False)
    with pytest.raises(StorageConfigurationError, match='identity changed'):
        plan.purge()
    for selected in deletion_stores:
        with selected.open() as handle:
            assert handle.sessions.get_session('same') is not None
            assert 'agent:before:cli:room' in handle.sessions.load_gateway_routing_entries()


@pytest.mark.integration
@pytest.mark.allow_network
def test_root_change_between_check_and_open_cannot_redirect_frozen_identity_write(deletion_stores, monkeypatch):
    from hermes_cli.profiles_deletion_storage import ProfileDeletion
    from hermes_cli import db_sessions as factory
    root, target, peer = deletion_stores
    plan = ProfileDeletion(target, root)
    original = factory.acquire_db
    def racing(settings, scope):
        retarget(root, 'peer')
        return original(settings, scope)
    with monkeypatch.context() as patch:
        patch.setattr(factory, 'acquire_db', racing)
        assert plan.purge_identity('before', False)
    with root.open() as handle:
        assert not handle.sessions.load_gateway_routing_entries()
    with peer.open() as handle:
        assert 'agent:before:cli:room' in handle.sessions.load_gateway_routing_entries()


@pytest.mark.integration
@pytest.mark.allow_network
def test_target_change_between_check_and_open_cannot_redirect_frozen_store_purge(deletion_stores, monkeypatch):
    from hermes_cli.profiles_deletion_storage import ProfileDeletion
    from hermes_cli import db_domains as factory
    root, target, peer = deletion_stores
    plan = ProfileDeletion(target, root)
    original = factory.acquire_domain
    def racing(name, settings, scope, **kwargs):
        retarget(target, 'peer')
        return original(name, settings, scope, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(factory, 'acquire_domain', racing)
        plan.purge()
    with target.open() as handle:
        assert handle.sessions.get_session('same') is None
    with peer.open() as handle:
        assert handle.sessions.get_session('same') is not None


@pytest.mark.integration
@pytest.mark.allow_network
@pytest.mark.parametrize('changed', ['root', 'target'])
def test_sqlite_to_pg_change_after_confirmation_is_refused(deletion_stores, changed):
    from hermes_cli.config_backend import write_config_key
    from hermes_cli.profiles_deletion_storage import ProfileDeletion, capture
    from hermes_db.errors import StorageConfigurationError
    root, target, peer = deletion_stores
    selected = root if changed == 'root' else target
    config_path = selected.scope.profile_home / 'config.yaml'
    write_config_key(config_path, 'storage.backend', 'sqlite')
    frozen = capture(selected.scope.profile_home)
    plan = ProfileDeletion(frozen if changed == 'target' else target,
                           frozen if changed == 'root' else root)
    write_config_key(config_path, 'storage.backend', 'postgresql')
    write_config_key(config_path, 'storage.postgresql.store_id', 'peer')
    with pytest.raises(StorageConfigurationError, match='identity changed'):
        plan.purge_identity('before', False)
    with pytest.raises(StorageConfigurationError, match='identity changed'):
        plan.purge()
    with peer.open() as handle:
        assert handle.sessions.get_session('same') is not None
        assert 'agent:before:cli:room' in handle.sessions.load_gateway_routing_entries()
