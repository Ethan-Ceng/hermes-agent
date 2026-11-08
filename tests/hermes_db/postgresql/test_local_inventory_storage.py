"""Owner inventory preserves backend identity independently of frozen agent policy."""

import pytest

pytest_plugins = ['tests.hermes_db.postgresql.test_surface_flow']
pytestmark = [pytest.mark.integration, pytest.mark.allow_network, pytest.mark.usefixtures('pg_sqlite_guard')]


async def make_owner(home, *, multiplex=False):
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner
    from gateway.session_authority import initialize_session_authority
    from hermes_cli.db_setup import _owning_profile
    with _owning_profile(home):
        runner = GatewayRunner(GatewayConfig(multiplex_profiles=multiplex))
        return await initialize_session_authority(runner, profile_id=str(home), instance_id='inventory-owner')


@pytest.mark.asyncio
async def test_inventory_project_uses_owning_profile_not_foreground_profile(surface_config, tmp_path):
    from gateway.session_local_inventory import session_inventory
    from gateway.session_policy import build_policy
    from hermes_cli import projects_db as projects
    from hermes_cli.db_setup import _owning_profile

    first, second = surface_config
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    for home, name in ((first, 'foreground project'), (second, 'owner project')):
        with _owning_profile(home), projects.connect_closing() as store:
            projects.create_project(store, name=name, slug='same', folders=[str(workspace)])
    owner = await make_owner(second, multiplex=True)
    with _owning_profile(first):
        policy = build_policy({'source': 'cli', 'cwd': str(workspace), 'toolsets': [], 'model': 'fixture'}, {})
        info = session_inventory(owner, policy, None, str(workspace))
    assert info['project']['name'] == 'owner project'
    assert owner.db.scope.store_id == 'surface-two'


@pytest.mark.asyncio
@pytest.mark.parametrize('safe_mode', [False, True])
async def test_bypass_inventory_keeps_pg_session_persistent_with_unreadable_config(surface_config, tmp_path, safe_mode):
    from gateway.session_contract import SessionActor
    from gateway.session_local import create_local_session
    from gateway.session_local_inventory import snapshot_info
    from hermes_cli.db_setup import _owning_profile, open_profile_db
    from hermes_db.errors import StorageConfigurationError

    home = surface_config[0]
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    owner = await make_owner(home)
    config = home / 'config.yaml'
    original = config.read_bytes()
    with _owning_profile(home):
        actor = SessionActor('local-user', str(home), frozenset({'session:create'}), 'local-test')
        ref = create_local_session(owner, actor, {
            'source': 'cli', 'cwd': str(workspace), 'request_id': 'frozen-bypass',
            'model': 'fixture', 'provider': 'custom', 'base_url': 'http://provider.invalid/v1',
            'toolsets': [], 'ignore_user_config': True, 'safe_mode': safe_mode})
    try:
        config.write_text('model: [private-broken-value', encoding='utf-8')
        with _owning_profile(home):
            info = await snapshot_info(owner, ref)
            assert info['project'] is None
            assert owner.db.scope.store_id == 'surface-one'
            assert owner.db.get_session(ref.session_id) is not None
            from gateway.session_local_inventory import _project
            with pytest.raises(StorageConfigurationError):
                _project(str(workspace))
    finally:
        config.write_bytes(original)
    with open_profile_db(home) as reopened:
        assert reopened.sessions.get_session(ref.session_id) is not None
    with open_profile_db(surface_config[1]) as peer:
        assert peer.sessions.get_session(ref.session_id) is None
