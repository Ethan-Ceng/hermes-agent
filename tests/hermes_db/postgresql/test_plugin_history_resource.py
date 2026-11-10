"""Published plugin history uses the selected real PG dataset without opening SQLite."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_plugin_history_closes_its_pg_view_and_preserves_the_owner_peer(pg_profiles):
    from hermes_cli.db_setup import open_profile_db
    from plugins.plugin_storage import session_history

    with pg_profiles('history-owner') as home, open_profile_db(home) as owner:
        owner.sessions.create_session('retained', source='test')
        owner.sessions.append_message('retained', 'user', 'history remains')
        with session_history(profile_home=home) as (history, identity):
            assert identity[0] == 'postgresql'
            assert history.get_messages('retained')[0]['content'] == 'history remains'
        assert not history.is_open
        owner.sessions.append_message('retained', 'assistant', 'peer remains open')
        assert owner.sessions.get_messages('retained')[-1]['content'] == 'peer remains open'
        assert not (home / 'state.db').exists()
