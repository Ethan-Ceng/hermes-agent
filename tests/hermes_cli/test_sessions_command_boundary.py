"""The retired command is refused before storage; supported sessions still run."""

import argparse
from pathlib import Path
from unittest.mock import Mock

import pytest


def _parser():
    from hermes_cli.subcommands.sessions import build_sessions_parser, cmd_sessions_lazy

    parser = argparse.ArgumentParser()
    build_sessions_parser(parser.add_subparsers(), cmd_sessions=cmd_sessions_lazy)
    return parser


@pytest.mark.parametrize("options", [[], ["--apply"], ["--json"], ["--legacy-main", "move"]])
def test_retired_command_is_rejected_before_storage(tmp_path, monkeypatch, options):
    from hermes_db import access

    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    opened = Mock(side_effect=AssertionError("retired command opened storage"))
    monkeypatch.setattr(access, "open_session_store", opened)
    with pytest.raises(SystemExit) as rejected:
        _parser().parse_args(["sessions", "repair-profiles", *options])
    assert rejected.value.code == 2
    opened.assert_not_called()
    assert list(home.iterdir()) == []


def test_supported_list_dispatches_against_selected_store(tmp_path, monkeypatch, capsys):
    from hermes_state import SessionDB

    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with SessionDB(db_path=home / "state.db") as db:
        db.create_session("boundary-session", "cli")
        db.set_session_title("boundary-session", "Boundary sample")
        db.append_message("boundary-session", "user", "ordinary history")
    args = _parser().parse_args(["sessions", "list"])
    args.func(args)
    assert "Boundary sample" in capsys.readouterr().out
    with SessionDB(db_path=home / "state.db") as db:
        assert db.get_messages("boundary-session")[0]["content"] == "ordinary history"
