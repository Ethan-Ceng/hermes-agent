"""Independent review repro: confirmation must freeze the selected dataset."""

import pytest
from tests.hermes_cli.test_profiles import profile_env
from tests.hermes_db.postgresql.test_profile_file_scope import _rename_home

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_delete_profile_refuses_database_retarget_during_confirmation(rename_home, pg_profiles, monkeypatch):
    from hermes_cli import profiles
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_cli.db_setup import open_profile_db
    with pg_profiles('two') as peer:
        with open_profile_db(peer) as handle:
            handle.sessions.create_session('other-profile-record', 'cli')
            handle.sessions.append_message('other-profile-record', 'user', 'must survive deletion of before')
    for name, result in (('_find_our_wrapper', None), ('_stop_profile_backends', None),
                         ('_notify_multiplexer', None), ('_purge_identity', True),
                         ('_retarget_active_profile', None)):
        monkeypatch.setattr(profiles, name, lambda *args, _result=result, **kwargs: _result)
    def confirm(_prompt):
        config = read_user_config_raw(rename_home / 'config.yaml')
        config['storage']['postgresql']['store_id'] = 'two'
        atomic_config_write(rename_home / 'config.yaml', config)
        return 'before'
    monkeypatch.setattr('builtins.input', confirm)
    failure = None
    try:
        profiles.delete_profile('before')
    except RuntimeError as error:
        failure = error
    with open_profile_db(peer) as handle:
        assert handle.sessions.get_session('other-profile-record') is not None, 'delete followed retargeted config and erased peer store'
    assert failure is not None and rename_home.exists(), 'retarget must refuse and preserve recovery files'
