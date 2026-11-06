"""Bundled dashboard discovery reads the selected store without SQLite fallback."""

from pathlib import Path
import sys
import threading

import pytest

from tests.hermes_db.contracts.test_surface_acquisition import _profile


@pytest.fixture
def achievements(monkeypatch, tmp_path):
    fastapi = pytest.importorskip('fastapi')
    from hermes_cli.web_server_dashboard import _discover_dashboard_plugins, _mount_one_plugin_api
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(tmp_path)
    try:
        plugins = _discover_dashboard_plugins([(Path(__file__).resolve().parents[3] / 'plugins', 'bundled')])
        plugin = next(p for p in plugins if p['name'] == 'hermes-achievements')
        assert _mount_one_plugin_api(fastapi.FastAPI(), plugin, set(), set())
        module = sys.modules['hermes_dashboard_plugin_hermes-achievements']
        monkeypatch.setattr(module, '_data_dir', lambda: tmp_path / 'statistics')
        yield module
    finally:
        reset_hermes_home_override(token)


def test_checkpoint_is_bound_to_store_even_with_identical_session_fingerprints(achievements, core_pair, native_registry, monkeypatch, tmp_path):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    with monkeypatch.context() as clock:
        clock.setattr('time.time', lambda: 1000.0)
        for db, count in zip(core_pair, (1, 3)):
            db.create_session('same', 'cli', model='model')
            db.set_session_title('same', 'same')
            for index in range(count):
                db.append_message('same', 'user', f'message {index}')
    token = set_hermes_home_override(tmp_path)
    try:
        _profile(tmp_path, 'one')
        first = achievements.scan_sessions()
        assert first['sessions'][0]['message_count'] == 1
        assert achievements.scan_sessions()['scan_meta']['sessions_reused'] == 1
        _profile(tmp_path, 'two')
        second = achievements.scan_sessions()
        assert second['sessions'][0]['message_count'] == 3
        assert second['scan_meta']['sessions_reused'] == 0
        assert achievements.scan_sessions()['scan_meta']['sessions_reused'] == 1
        assert not (tmp_path / 'state.db').exists()
    finally:
        reset_hermes_home_override(token)


def test_unavailable_native_scan_never_creates_sqlite(achievements, unavailable_native, tmp_path):
    _profile(tmp_path, 'one')
    result = achievements.scan_sessions()
    assert result['scan_meta']['mode'] == 'failed'
    assert 'storage unavailable' in result['error']
    assert not (tmp_path / 'state.db').exists()


def test_background_scan_keeps_the_initiating_profile(achievements, monkeypatch, tmp_path):
    from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override
    entered, release = threading.Event(), threading.Event()
    observed = []

    def scan(**kwargs):
        entered.set()
        assert release.wait(10)
        observed.append(get_hermes_home())

    monkeypatch.setattr(achievements, '_run_scan_and_update_cache', scan)
    token = set_hermes_home_override(tmp_path / 'initiator')
    try:
        achievements._start_background_scan()
        assert entered.wait(10)
        other = set_hermes_home_override(tmp_path / 'other')
        try:
            release.set()
            achievements._BACKGROUND_SCAN_THREAD.join(10)
        finally:
            reset_hermes_home_override(other)
        assert observed == [tmp_path / 'initiator']
    finally:
        release.set()
        reset_hermes_home_override(token)
