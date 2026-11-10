"""Initialization and ordinary startup check required capabilities before DDL."""

from contextlib import contextmanager
from dataclasses import replace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def settings(postgres_test_config, postgres_schema):
    return replace(postgres_test_config.settings, schema=postgres_schema)


@contextmanager
def _capture_ddl(engine, *, hide_extension=False):
    from sqlalchemy import event
    ddl = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith(('CREATE ', 'ALTER ', 'DROP ')):
            ddl.append(statement.lstrip().splitlines()[0])
        # Fault injection leaves the administrator's real extension untouched.
        if hide_extension and normalized.startswith('SELECT') and 'pg_extension' in statement:
            return 'SELECT NULL::text AS schema_name, NULL::text AS version WHERE false', {}
        return statement, parameters

    event.listen(engine, 'before_cursor_execute', observe, retval=True)
    try:
        yield ddl
    finally:
        event.remove(engine, 'before_cursor_execute', observe)


def test_upgrade_checks_extension_before_creating_tables(settings, postgres_engine):
    from hermes_db.errors import StorageSchemaError
    from hermes_db.schema import upgrade_schema
    with _capture_ddl(postgres_engine, hide_extension=True) as ddl:
        with pytest.raises(StorageSchemaError, match='pg_trgm'):
            upgrade_schema(settings)
        count = len(ddl)
        assert count == 0, 'Missing extension must be rejected before any schema DDL'


def test_current_revision_is_not_ready_when_extension_is_missing(settings, postgres_engine, tmp_path, monkeypatch):
    from hermes_cli import db_setup
    from hermes_db.errors import StorageSchemaError
    from hermes_cli.db_sessions import acquire_db
    from hermes_cli.db_diagnostics import configured_probe
    from hermes_db.schema import schema_status, upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings
    upgrade_schema(settings)
    scope = DatabaseScope(tmp_path, 'startup')
    monkeypatch.setattr(db_setup, 'resolve_db_configuration', lambda home: (DatabaseSettings('postgresql', settings), scope))
    monkeypatch.setattr(db_setup, 'storage_backend', lambda home: 'postgresql')
    with _capture_ddl(postgres_engine, hide_extension=True) as ddl:
        status = schema_status(settings)
        assert not status['ready']
        assert status['missing_extensions'] == ['pg_trgm']
        assert 'CREATE EXTENSION IF NOT EXISTS pg_trgm' in status['action_required']
        with pytest.raises(StorageSchemaError, match='CREATE EXTENSION IF NOT EXISTS pg_trgm'):
            acquire_db(DatabaseSettings('postgresql', settings), scope)
        assert configured_probe(tmp_path) == {'backend': 'postgresql', 'status': 'degraded', 'detail': 'StorageSchemaError'}
        assert len(ddl) == 0


@pytest.mark.parametrize('action', ['status', 'upgrade'])
def test_cli_reports_extension_remediation_before_ddl(settings, postgres_engine, tmp_path, monkeypatch, capsys, action):
    from types import SimpleNamespace
    from hermes_cli import db_setup
    from hermes_cli.db_cmd import run_db_command
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings
    monkeypatch.setattr(db_setup, 'resolve_db_configuration',
        lambda: (DatabaseSettings('postgresql', settings), DatabaseScope(tmp_path, 'startup')))
    with _capture_ddl(postgres_engine, hide_extension=True) as ddl:
        assert run_db_command(SimpleNamespace(db_action=action)) == 1
        output = capsys.readouterr()
        assert 'CREATE EXTENSION IF NOT EXISTS pg_trgm' in output.out + output.err
        assert len(ddl) == 0


def test_healthy_factory_startup_checks_capabilities_without_ddl(settings, postgres_engine, tmp_path):
    from hermes_cli.db_sessions import acquire_db
    from hermes_db.schema import schema_status, upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings
    upgrade_schema(settings)
    with _capture_ddl(postgres_engine) as ddl:
        with acquire_db(DatabaseSettings('postgresql', settings), DatabaseScope(tmp_path, 'startup')):
            status = schema_status(settings)
            assert status['ready']
            assert status['missing_extensions'] == []
        assert len(ddl) == 0
