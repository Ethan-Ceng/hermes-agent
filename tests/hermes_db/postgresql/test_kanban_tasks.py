"""Kanban task/graph contracts; all filesystem roots and PG namespaces are isolated."""

import pytest

from hermes_db.domains.kanban import rules as kanban_rules
from hermes_cli import kanban_db_connect as kbc

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def kanban_profiles(pg_profiles, tmp_path, monkeypatch):
    from pathlib import Path
    import hermes_constants
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(hermes_constants, "_default_hermes_root_memo", None)
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(tmp_path / "shared-kanban"))
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "path-override" / "kanban.db"))
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    return pg_profiles


def test_task_graph_comments_and_events_use_pg(kanban_profiles):
    from hermes_cli import kanban_db as kb
    with kanban_profiles("one"):
        kb.create_board("alpha")
        with kbc.connect_closing(board="alpha") as store:
            parent = kb.create_task(store, title="父\x00🙂", body="body\x00", workspace_kind="scratch")
            child = kb.create_task(store, title="child", parents=[parent], workspace_kind="scratch")
            assert kb.get_task(store, parent).title == "父\x00🙂"
            assert kb.get_task(store, child).status == "todo"
            assert kb.parent_ids(store, child) == [parent]
            assert kb.child_ids(store, parent) == [child]
            with pytest.raises(ValueError, match="cycle"):
                kb.link_tasks(store, child, parent)
            assert kb.unlink_tasks(store, parent, child)
            assert kb.get_task(store, child).status == "ready"
            comment_id = kb.add_comment(store, parent, "author", "comment\x00🙂")
            assert kb.list_comments(store, parent)[0].body == "comment\x00🙂"
            assert kb.list_comments(store, parent)[0].task_id == parent
            assert kb.list_comments_after(store, parent, after_id=comment_id) == []
            assert kb.list_events(store, parent)[0].kind == "created"
            assert kb.list_events(store, parent)[0].task_id == parent
            assert kb.edit_task(store, parent, title="edited", priority=7)
            assert kb.list_tasks(store, order_by="priority")[0].id == parent
            assert kb.task_graph_context(store, parent) == {"parents": [], "children": []}
            assert kb.delete_task(store, child)
            assert kb.get_task(store, child) is None


def test_same_task_ids_are_isolated_and_board_recreate_has_new_generation(kanban_profiles, monkeypatch):
    from hermes_cli import kanban_db as kb
    monkeypatch.setattr(kanban_rules, "_new_task_id", lambda: "t_same")
    with kanban_profiles("one"):
        for board in ("alpha", "beta"):
            kb.create_board(board)
            with kbc.connect_closing(board=board) as store:
                assert kb.create_task(store, title=board, workspace_kind="scratch") == "t_same"
        with kbc.connect_closing(board="alpha") as store:
            assert kb.get_task(store, "t_same").title == "alpha"
        kb.remove_board("alpha", archive=True)
        kb.create_board("alpha")
        with kbc.connect_closing(board="alpha") as store:
            assert kb.get_task(store, "t_same") is None
    with kanban_profiles("two"):
        kb.create_board("beta")
        with kbc.connect_closing(board="beta") as store:
            assert kb.get_task(store, "t_same") is None
            kb.create_task(store, title="second-store", workspace_kind="scratch")
    with kanban_profiles("one"), kbc.connect_closing(board="beta") as store:
        assert kb.get_task(store, "t_same").title == "beta"


def test_board_metadata_and_stale_handle_are_fenced(kanban_profiles):
    from hermes_cli import kanban_db as kb
    with kanban_profiles("one"):
        kb.create_board("alpha", name="Alpha\x00🙂", description="exact\x00")
        kb.set_current_board("alpha")
        assert kb.get_current_board() == "alpha"
        with kbc.connect_closing() as stale:
            old_generation = stale.board_id
            kb.create_task(stale, title="old", workspace_kind="scratch")
            kb.remove_board("alpha")
            assert kb.get_current_board() == "default"
            with pytest.raises(ValueError, match="archived"), kbc.connect_closing(board="alpha"):
                pytest.fail("archived Boards must not reopen themselves")
            kb.create_board("alpha", name="New")
            with pytest.raises(ValueError, match="removed or archived"):
                kb.create_task(stale, title="stale", workspace_kind="scratch")
        with kbc.connect_closing(board="alpha") as current:
            assert current.board_id != old_generation
            assert kb.list_tasks(current) == []
        kb.write_board_metadata("alpha", description="new\x00🙂")
        assert kb.read_board_metadata("alpha")["description"] == "new\x00🙂"
        assert [item["slug"] for item in kb.list_boards()] == ["default", "alpha"]
        with kbc.connect_closing(board="alpha") as stale:
            kb.remove_board("alpha", archive=False)
            with pytest.raises(ValueError, match="removed or archived"):
                kb.add_comment(stale, "any", "a", "removed")
        assert not kb.board_exists("alpha")
    with kanban_profiles("two"):
        assert [item["slug"] for item in kb.list_boards()] == ["default"]


def test_atomic_decomposition_origin_and_specification(kanban_profiles, monkeypatch):
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_graph import decompose_triage_task
    from hermes_db.errors import StorageConflictError
    with kanban_profiles("one"), kbc.connect_closing() as store:
        root = kb.create_task(store, title="root", triage=True, workspace_kind="dir", workspace_path="workspace",
                              session_id="origin", tenant="tenant")
        generated = iter(["t_fresh", root])
        with monkeypatch.context() as collision, pytest.raises(StorageConflictError):
            collision.setattr(kanban_rules, "_new_task_id", lambda: next(generated))
            decompose_triage_task(store, root, root_assignee="orchestrator", children=[
                {"title": "first"}, {"title": "collides after first insert"}])
        assert [task.id for task in kb.list_tasks(store)] == [root]
        assert kb.get_task(store, root).status == "triage"
        children = [{"title": "first"}, {"title": "second", "parents": [0]}]
        ids = decompose_triage_task(store, root, root_assignee="orchestrator", children=children, author="creator")
        assert [kb.get_task(store, tid).status for tid in ids] == ["ready", "todo"]
        assert kb.parent_ids(store, root) == sorted(ids)
        assert kb.get_task(store, ids[1]).session_id == "origin"
        assert kb.get_task(store, ids[1]).workspace_path == "workspace"
        assert decompose_triage_task(store, root, root_assignee=None, children=children) is None
        assert kb.list_comments(store, root)[0].author == "creator"
        triage = kb.create_task(store, title="rough", triage=True, workspace_kind="scratch")
        assert kb.specify_triage_task(store, triage, title="clear", assignee="coder", author="creator")
        assert kb.get_task(store, triage).status == "ready"
        assert kb.list_events(store, triage)[1].kind == "specified"


def test_concurrent_idempotency_and_opposing_graph_edges(kanban_profiles):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Barrier
    from hermes_cli import kanban_db as kb
    with kanban_profiles("one"), kbc.connect_closing() as store:
        barrier = Barrier(2)
        def create():
            barrier.wait(timeout=10)
            return kb.create_task(store, title="once", workspace_kind="scratch", idempotency_key="same\x00🙂")
        with ThreadPoolExecutor(max_workers=2) as workers:
            ids = [future.result() for future in [workers.submit(copy_context().run, create) for _ in range(2)]]
        assert ids[0] == ids[1]
        assert len(kb.list_tasks(store)) == 1
        other = kb.create_task(store, title="other", workspace_kind="scratch")
        def link(parent, child):
            barrier.wait(timeout=10)
            try:
                kb.link_tasks(store, parent, child)
                return "linked"
            except ValueError as error:
                assert "cycle" in str(error)
                return "cycle"
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = [future.result() for future in [workers.submit(copy_context().run, link, p, c)
                       for p, c in ((ids[0], other), (other, ids[0]))]]
        assert sorted(results) == ["cycle", "linked"]
        graph = kb.task_graph_contexts(store, [*ids, other])
        assert sum(len(value["parents"]) for value in graph.values()) == 1


def test_project_inheritance_overrides_sort_and_process_recovery(kanban_profiles, tmp_path):
    import subprocess
    import sys
    from hermes_cli import kanban_db as kb, projects_db as pdb
    from hermes_db.infra.postgresql.engine import close_engines
    with kanban_profiles("one") as home:
        with pdb.connect_closing() as projects:
            project_id = pdb.create_project(projects, name="Repo", slug="repo", primary_path=str(tmp_path / "repo"))
        kb.create_board("alpha", project_id=project_id)
        with kbc.connect_closing(board="alpha") as store:
            inherited = kb.create_task(store, title="inherited", assignee="coder", skills=["skill"], goal_mode=True)
            task = kb.get_task(store, inherited)
            assert task.project_id == project_id and task.workspace_kind == "worktree"
            assert task.workspace_path == str(tmp_path / "repo" / ".worktrees" / inherited)
            assert task.skills == ["skill"] and task.goal_mode
            child = kb.create_task(store, title="scratch", workspace_kind="scratch", creator_task_id=inherited)
            assert kb.get_task(store, child).project_id is None
            assert kb.set_model_override(store, child, "model", "provider")
            assert kb.set_reasoning_effort(store, child, "none")
            assert kb.assign_task(store, child, "reviewer")
            assert kb.get_task(store, child).reasoning_effort == "none"
            assert kb.get_task(store, child).provider_override == "provider"
            assert kb.board_stats(store)["by_status"] == {"ready": 2}
            assert [task.id for task in kb.list_tasks(store, order_by="title")] == [inherited, child]
            with pytest.raises(ValueError, match="order_by"):
                kb.list_tasks(store, order_by="untrusted")
        close_engines()
        code = r'''
import sys, sqlite3
def reject(*args, **kwargs):
    raise AssertionError('SQLite in PG Kanban child')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
with kbc.connect_closing(board='alpha') as store:
    assert kb.get_task(store, sys.argv[2]).title == 'inherited'
    assert kb.read_board_metadata('alpha')['project_id'] == sys.argv[3]
    kb.add_comment(store, sys.argv[2], 'child', 'restarted\x00🙂')
'''
        result = subprocess.run([sys.executable, "-c", code, str(home), inherited, project_id], capture_output=True,
                                text=True, check=False, timeout=30)
        assert result.returncode == 0, result.stderr
        with kbc.connect_closing(board="alpha") as store:
            assert kb.list_comments(store, inherited)[0].body == "restarted\x00🙂"


def test_cli_basic_task_consumers_work_with_pg(kanban_profiles):
    import json
    from hermes_cli import kanban as cli, kanban_db as kb
    with kanban_profiles("one"):
        kb.create_board("cli-board")
        with kb.scoped_current_board("cli-board"):
            created = json.loads(cli.run_slash('create "from cli" --workspace scratch --json'))
            task_id = created["id"]
            assert json.loads(cli.run_slash("list --json"))[0]["id"] == task_id
            assert "Edited" in cli.run_slash(f"edit {task_id} --title edited")
            assert json.loads(cli.run_slash("list --json"))[0]["title"] == "edited"
            assert json.loads(cli.run_slash("stats --json"))["by_status"] == {"ready": 1}


def test_bound_resource_uses_owner_after_context_change_and_errors_propagate(kanban_profiles):
    from sqlalchemy import text
    from hermes_cli import kanban_db as kb
    from hermes_db.errors import StorageError
    with kanban_profiles("one") as home:
        kb.create_board("alpha", default_workdir=str(home / "workspace"))
        store = kbc.connect(board="alpha")
        task_id = kb.create_task(store, title="owner", workspace_kind="dir")
    try:
        with kanban_profiles("two"):
            assert kb.edit_task(store, task_id, title="still owner")
            new_id = kb.create_task(store, title="bound", workspace_kind="dir")
            assert kb.get_task(store, new_id).workspace_path == str(home / "workspace")
            assert not kb.board_exists("alpha")
        with kanban_profiles("one"), kbc.connect_closing(board="alpha") as reopened:
            assert kb.get_task(reopened, task_id).title == "still owner"
            assert reopened._transactions.engine.pool.checkedout() == 0
            with reopened.write() as conn:
                schema = conn.dialect.identifier_preparer.quote(reopened.settings.postgresql.schema)
                conn.execute(text(f"DROP TABLE {schema}.kanban_comments"))
            with pytest.raises(StorageError):
                kb.list_comments(reopened, task_id)
    finally:
        store.close()


def test_file_configuration_failure_does_not_reallocate_board(kanban_profiles, monkeypatch):
    from hermes_cli import kanban_db as kb, kanban_db_boards as board_files
    with kanban_profiles("one"):
        def file_failure(*args, **kwargs):
            raise OSError("file configuration write failed")
        with monkeypatch.context() as failure:
            failure.setattr(board_files, "_write_metadata_file", file_failure)
            with pytest.raises(OSError, match="file configuration write failed"):
                kb.create_board("alpha")
        with kbc.connect_closing(board="alpha") as resource:
            generation = resource.board_id
        kb.create_board("alpha", name="Recovered")
        with kbc.connect_closing(board="alpha") as resource:
            assert resource.board_id == generation
        assert kb.board_metadata_path("alpha").is_file()
        assert kb.read_board_metadata("alpha")["name"] == "Recovered"
