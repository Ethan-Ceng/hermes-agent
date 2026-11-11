"""CLI schema operations are explicit and resolve the selected Profile."""

import argparse
import json

import pytest

from hermes_cli.db_parser import build_db_parser
from hermes_db.errors import StorageUnavailableError
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings, PostgresSettings


def _parse(*args):
    parser = argparse.ArgumentParser()
    build_db_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(args)


def test_top_level_cli_reaches_db_commands():
    from hermes_cli.main import _build_cli_parser

    parser, _ = _build_cli_parser()
    args = parser.parse_args(["db", "status"])
    assert args.db_action == "status"
    assert callable(args.func)


def test_sqlite_status_reports_missing_until_explicit_upgrade(tmp_path, monkeypatch, capsys):
    from hermes_cli import db_setup

    monkeypatch.setattr(db_setup, "resolve_db_configuration", lambda profile_home=None: (DatabaseSettings(), DatabaseScope(tmp_path)))
    args = _parse("db", "status")
    assert args.func(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["backend"] == "sqlite"
    assert report["ready"] is False
    assert not (tmp_path / "state.db").exists()
    args = _parse("db", "upgrade")
    assert args.func(args) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    assert (tmp_path / "state.db").exists()


@pytest.mark.parametrize("action", ["status", "upgrade"])
def test_pg_operations_consume_resolved_profile_without_exposing_dsn(tmp_path, monkeypatch, capsys, action):
    pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from hermes_cli import db_setup
    from hermes_db import schema

    pg = PostgresSettings("postgresql://u:private-password@localhost/db", "hermes")
    monkeypatch.setattr(db_setup, "resolve_db_configuration", lambda: (
        DatabaseSettings("postgresql", pg), DatabaseScope(tmp_path, "store-a")))
    calls = []

    def operation(settings):
        calls.append(settings)
        return {"backend": "postgresql", "schema": settings.schema, "ready": True}

    monkeypatch.setattr(schema, {"status": "schema_status", "upgrade": "upgrade_schema"}[action], operation)
    args = _parse("db", action)
    assert args.func(args) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["store_id"] == "store-a"
    assert "private-password" not in output
    assert calls == [pg]


def test_connection_failure_is_reported_and_never_changes_backend(tmp_path, monkeypatch, capsys):
    pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from hermes_cli import db_setup
    from hermes_db import schema

    monkeypatch.setattr(db_setup, "resolve_db_configuration", lambda: (
        DatabaseSettings("postgresql", PostgresSettings("postgresql://localhost/unused", "hermes")),
        DatabaseScope(tmp_path, "stable")))

    def unavailable(settings):
        raise StorageUnavailableError("PostgreSQL connection unavailable")

    monkeypatch.setattr(schema, "schema_status", unavailable)
    args = _parse("db", "status")
    assert args.func(args) == 1
    assert "PostgreSQL connection unavailable" in capsys.readouterr().err
    assert not (tmp_path / "state.db").exists()


def test_db_command_consumes_the_current_profiles_actual_config(tmp_path, capsys):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    (tmp_path / "config.yaml").write_text("storage: {backend: unknown}\n", encoding="utf-8")
    token = set_hermes_home_override(tmp_path)
    try:
        args = _parse("db", "status")
        assert args.func(args) == 1
    finally:
        reset_hermes_home_override(token)
    assert "backend must be sqlite or postgresql" in capsys.readouterr().err
    assert not (tmp_path / "state.db").exists()
