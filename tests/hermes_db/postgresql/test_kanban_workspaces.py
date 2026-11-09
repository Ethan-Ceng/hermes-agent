"""Workspace adapter contracts; full concurrent lifecycle remains a Task 9 gate."""

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_workspace_fields_and_cross_board_live_reference_preserve_content(pg_profiles):
    from hermes_db.domains.kanban.postgres.queries import kanban as repo
    with pg_profiles("one"):
        kb.create_board("alpha")
        kb.create_board("beta")
        with kbc.connect_closing(board="alpha") as first, kbc.connect_closing(board="beta") as second:
            tid = kb.create_task(first, title="first", workspace_kind="scratch")
            other = kb.create_task(second, title="second", workspace_kind="scratch")
            path = kb.workspaces_root(board="alpha") / tid
            path.mkdir(parents=True)
            (path / "proof.txt").write_text("retained", encoding="utf-8")
            workspace.set_workspace_path(first, tid, path)
            workspace.set_branch_name(first, tid, "branch\x00🙂")
            workspace.set_workspace_path(second, other, path)
            assert kb.get_task(first, tid).branch_name == "branch\x00🙂"
            assert kb._scratch_workspace(first, tid) == path
            assert workspace._workspace_in_use_by_other(first, tid, path) == "shared"
            # Seed the terminal precondition for this adapter; completion itself has a separate gate.
            with first.write() as conn:
                repo.task_update(conn, first, tid, status="done")
            kb._cleanup_workspace(first, tid)
            assert (path / "proof.txt").read_text(encoding="utf-8") == "retained"
            assert kb.delete_task(second, other)
            kb._cleanup_workspace(first, tid)
            assert not path.exists()


def test_resource_owner_binds_workspace_after_ambient_profile_change(pg_profiles):
    with pg_profiles("one") as home:
        store = kbc.connect()
        tid = kb.create_task(store, title="bound", workspace_kind="scratch")
        path = home / "kanban" / "workspaces" / tid
        workspace.set_workspace_path(store, tid, path)
    try:
        with pg_profiles("two"):
            assert kb._scratch_workspace(store, tid) == Path(path)
            assert kb.get_task(store, tid).workspace_path == str(path)
    finally:
        store.close()


@pytest.mark.parametrize("reference", ["create", "set"])
def test_cleanup_fences_concurrent_cross_board_workspace_references(pg_profiles, monkeypatch, reference):
    from hermes_db.errors import StorageBusyError
    from hermes_db.domains.kanban.postgres.queries import kanban as repo
    with pg_profiles("one"):
        kb.create_board("other")
        with kbc.connect_closing() as first, kbc.connect_closing(board="other") as second:
            task = kb.create_task(first, title="finished", workspace_kind="scratch")
            path = kb.workspaces_root() / task
            path.mkdir(parents=True)
            workspace.set_workspace_path(first, task, path)
            other = kb.create_task(second, title="new reference")
            with first.write() as conn:
                repo.task_update(conn, first, task, status="done")
            outcomes = []
            original = workspace.shutil.rmtree

            def remove(directory, **kwargs):
                assert first._transactions.engine.pool.checkedout() == 0
                try:
                    if reference == "create":
                        kb.create_task(second, title="must not race deletion", workspace_kind="dir", workspace_path=str(path))
                    else:
                        workspace.set_workspace_path(second, other, path)
                    outcomes.append("allowed")
                except StorageBusyError:
                    outcomes.append("fenced")
                original(directory, **kwargs)

            monkeypatch.setattr(workspace.shutil, "rmtree", remove)
            kb._cleanup_workspace(first, task)
            assert outcomes == ["fenced"]
            assert not path.exists()
            assert kb.get_task(second, other).workspace_path is None
            assert len(kb.list_tasks(second)) == 1
            workspace.set_workspace_path(second, other, path)
            assert kb.get_task(second, other).workspace_path == str(path)


def test_cleanup_fences_new_live_child_and_interruption_survives_reopen(pg_profiles, monkeypatch):
    from hermes_db.errors import StorageBusyError
    from hermes_db.domains.kanban.postgres.queries import kanban as repo
    with pg_profiles("one"):
        with kbc.connect_closing() as first, kbc.connect_closing() as second:
            parent = kb.create_task(first, title="finished", workspace_kind="scratch")
            child = kb.create_task(second, title="new child")
            path = kb.workspaces_root() / parent
            path.mkdir(parents=True)
            workspace.set_workspace_path(first, parent, path)
            with first.write() as conn:
                repo.task_update(conn, first, parent, status="done")
            fenced = []

            def interrupted_remove(directory):
                assert first._transactions.engine.pool.checkedout() == 0
                with pytest.raises(StorageBusyError, match="cleanup is pending"):
                    kb.link_tasks(second, parent, child)
                fenced.append(True)
                raise OSError("test interrupted filesystem operation")

            monkeypatch.setattr(workspace.shutil, "rmtree", interrupted_remove)
            kb._cleanup_workspace(first, parent)
            assert fenced == [True]
            assert kb.parent_ids(second, child) == []
        with kbc.connect_closing() as reopened:
            assert path.exists()
            with pytest.raises(StorageBusyError, match="cleanup is pending"):
                workspace.set_workspace_path(reopened, child, path)
