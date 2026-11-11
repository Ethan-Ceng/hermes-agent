"""The existing database command is an explicit SQLite lifecycle entry."""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

from hermes_cli.db_cmd import run_db_command
from hermes_state import SessionDB
from hermes_state_common import SCHEMA_VERSION


def test_sqlite_status_and_explicit_upgrade(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "state.db"

    def invoke(action):
        result = run_db_command(SimpleNamespace(db_action=action))
        return result, json.loads(capsys.readouterr().out)

    code, report = invoke("status")
    assert code == 1 and not report["ready"]
    assert not path.exists()
    code, report = invoke("upgrade")
    assert code == 0 and report["ready"]
    with SessionDB.open_existing(path) as db:
        db.create_session("preserved", source="cli")
        db.append_message("preserved", role="user", content="retain me")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION - 1,))
    code, report = invoke("status")
    assert code == 1 and not report["ready"]
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION - 1
    for _ in range(2):
        code, report = invoke("upgrade")
        assert code == 0 and report["ready"]
    with SessionDB.open_existing(path, read_only=True) as db:
        assert db.get_messages("preserved")[0]["content"] == "retain me"


def test_new_profile_has_a_ready_session_database(tmp_path, monkeypatch):
    from pathlib import Path

    from hermes_cli.db_setup import open_profile_sessions
    from hermes_cli.profiles import create_profile

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    launch = tmp_path / ".hermes"
    launch.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(launch))
    profile = create_profile("ledger", no_alias=True, no_skills=True)
    assert not (launch / "state.db").exists()
    with open_profile_sessions(profile) as db:
        db.create_session("new-profile", source="cli")
    with open_profile_sessions(profile, read_only=True) as db:
        assert db.get_session("new-profile") is not None
