"""SQLite-only console maintenance never opens or repairs a PG profile's old file."""

from types import SimpleNamespace

import pytest

from tests.hermes_db.contracts.test_surface_acquisition import _profile


@pytest.mark.parametrize('command', ['sessions optimize --force', 'sessions repair'])
def test_console_refuses_sqlite_maintenance_for_postgresql(command, unavailable_native, tmp_path):
    from hermes_cli.console_engine import HermesConsoleEngine
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    _profile(tmp_path, 'one')
    old_file = tmp_path / 'state.db'
    old_file.write_bytes(b'old SQLite file, preserved')
    token = set_hermes_home_override(tmp_path)
    try:
        result = HermesConsoleEngine().execute(command, confirmed=True)
        assert result.status == 'error'
        assert 'local SQLite' in result.output
        assert old_file.read_bytes() == b'old SQLite file, preserved'
    finally:
        reset_hermes_home_override(token)


def test_legacy_adopt_refuses_pg_before_reading_an_old_file(unavailable_native, tmp_path, capsys):
    from hermes_cli.sessions_adopt import cmd_adopt
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    _profile(tmp_path, 'one')
    token = set_hermes_home_override(tmp_path)
    try:
        assert cmd_adopt(SimpleNamespace()) == 1
        assert 'SQLite' in capsys.readouterr().out
        assert not (tmp_path / 'state.db').exists()
    finally:
        reset_hermes_home_override(token)
