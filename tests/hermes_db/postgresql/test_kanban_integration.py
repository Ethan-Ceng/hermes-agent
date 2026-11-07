"""Actual Kanban CLI consumers on selected PG storage; no Board SQLite files."""

from pathlib import Path
from types import SimpleNamespace
import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_ops

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_boards_cli_counts_actual_pg_rows(pg_profiles):
    from hermes_cli.kanban_boards import _board_task_counts
    with pg_profiles("one"), kbc.connect_closing() as store:
        kb.create_task(store, title="listed")
        assert _board_task_counts("default") == {"ready": 1}


def test_sqlite_repair_cannot_touch_existing_file_when_pg_is_selected(pg_profiles):
    from hermes_db.errors import StorageConfigurationError
    with pg_profiles("one") as home:
        existing = home / "kanban.db"
        existing.write_bytes(b"preserved old dataset")
        with pytest.raises(StorageConfigurationError, match="SQLite.*PostgreSQL"):
            kbc.repair_db()
        assert existing.read_bytes() == b"preserved old dataset"


def test_cli_watch_and_gc_use_selected_board_and_persist_cleanup(pg_profiles, monkeypatch, capsys):
    with pg_profiles("one"), kbc.connect_closing() as store:
        task = kb.create_task(store, title="watch", assignee="default", tenant="team")

        def poll(interval, tick):
            kb.add_comment(store, task, "worker", "live")
            tick()
            return 0

        monkeypatch.setattr(kanban_ops, "_poll_loop", poll)
        args = SimpleNamespace(kinds="commented", assignee="default", tenant="team", interval=.1)
        assert kanban_ops._cmd_watch(args) == 0
        output = capsys.readouterr().out
        assert task in output and "commented" in output
        assert kb.archive_task(store, task)
        workspace = kb.workspaces_root() / task
        workspace.mkdir(parents=True)
        (workspace / "discard.txt").write_text("scratch", encoding="utf-8")
        assert kanban_ops._cmd_gc(SimpleNamespace(event_retention_days=0, log_retention_days=0)) == 0
        assert not workspace.exists()
        assert "1 workspace(s)" in capsys.readouterr().out
    with pg_profiles("one"), kbc.connect_closing() as reopened:
        assert kb.get_task(reopened, task).status == "archived"
        assert Path(kb.get_task(reopened, task).workspace_path) == workspace
