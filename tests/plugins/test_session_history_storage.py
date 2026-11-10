"""The published history context reads the selected dataset and releases native resources."""

from contextlib import nullcontext
import sqlite3

import pytest


@pytest.mark.parametrize('abort_scan', [False, True])
def test_native_history_context_keeps_messages_and_closes_even_after_scan_failure(tmp_path, abort_scan):
    from hermes_state import SessionDB
    from plugins.plugin_storage import session_history

    with SessionDB(tmp_path / 'state.db') as seed:
        seed.create_session('retained', source='test')
        seed.append_message('retained', 'user', 'history remains')
    class ScanFailed(Exception):
        pass
    with pytest.raises(ScanFailed) if abort_scan else nullcontext():
        with session_history(profile_home=tmp_path) as (store, identity):
            assert identity == (tmp_path / 'state.db').resolve()
            assert store.get_messages('retained')[0]['content'] == 'history remains'
            connection = store._connections._conn
            if abort_scan:
                raise ScanFailed()
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute('SELECT 1')
