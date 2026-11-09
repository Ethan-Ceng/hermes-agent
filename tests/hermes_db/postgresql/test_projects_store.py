"""Real Projects facade and UI consumers with all SQLite connections forbidden."""

from contextlib import contextmanager
from dataclasses import replace
import json
import sqlite3

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def project_profiles(postgres_test_config, postgres_schema, tmp_path, monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from hermes_cli.config import atomic_config_write
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_db.schema import upgrade_schema
    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    upgrade_schema(pg)

    @contextmanager
    def owner(name):
        home = tmp_path / name
        home.mkdir(exist_ok=True)
        atomic_config_write(home / "config.yaml", {"storage": {"backend": "postgresql", "postgresql": {
            "schema": pg.schema, "store_id": name, "pool_size": 2, "max_overflow": 0, "connection_budget": 2}}})
        (home / ".env").write_text("HERMES_POSTGRES_DSN=" + json.dumps(pg.dsn) + "\n", encoding="utf-8")
        home_token = set_hermes_home_override(home)
        secret_token = set_secret_scope({"HERMES_POSTGRES_DSN": pg.dsn}, profile_home=str(home))
        try:
            yield home
        finally:
            reset_secret_scope(secret_token)
            reset_hermes_home_override(home_token)

    def reject(*args, **kwargs):
        pytest.fail("Projects PG business process must never connect to SQLite")
    monkeypatch.setattr(sqlite3, "connect", reject)
    return owner


def test_projects_folders_meta_cache_and_scope(project_profiles, tmp_path, monkeypatch):
    from hermes_cli import projects_db as pdb
    owner = project_profiles
    first, second = str(tmp_path / "repo-a"), str(tmp_path / "repo-b")
    with monkeypatch.context() as ids:
        ids.setattr(pdb.secrets, "token_hex", lambda count: "same-id")
        for name in ("one", "two"):
            with owner(name), pdb.connect_closing() as store:
                project_id = pdb.create_project(store, name="中文\x00🙂", slug="same", folders=[first])
                assert project_id == "p_same-id"
    with owner("one") as home, pdb.connect_closing() as store:
        assert not hasattr(store, "execute")
        assert pdb.get_project(store, "SAME").name == "中文\x00🙂"
        assert pdb.get_project(store, "\x00") is None
        assert pdb.add_folder(store, project_id, second, label="label\x00", is_primary=True) == second
        project = pdb.get_project(store, project_id)
        assert project.primary_path == second
        assert sum(folder.is_primary for folder in project.folders) == 1
        assert pdb.project_for_path(store, second + "/nested").id == project_id
        assert pdb.remove_folder(store, project_id, second)
        assert pdb.get_project(store, project_id).primary_path == first
        pdb.update_project(store, project_id, description="desc\x00", icon="🙂", board_slug="board")
        pdb.set_active(store, project_id)
        assert pdb.get_active_id(store) == project_id
        pdb.record_discovered_repos(store, [(first, "cache\x00")], policy_key="a")
        assert pdb.list_discovered_repos(store)[0]["label"] == "cache\x00"
        assert pdb.reconcile_discovered_repos_policy(store, "b")
        assert pdb.list_discovered_repos(store) == []
        assert pdb.get_discovery_policy_key(store) == "b"
        assert pdb.archive_project(store, project_id)
        assert pdb.list_projects(store) == []
        assert pdb.restore_project(store, project_id)
        assert len(pdb.list_projects(store)) == 1
        assert not (home / "projects.db").exists()
    with owner("two"), pdb.connect_closing() as store:
        assert pdb.get_project(store, project_id).description is None
        assert pdb.get_active_id(store) is None
        assert pdb.get_discovery_policy_key(store) is None
    from hermes_db.backends.postgresql.engine import close_engines
    close_engines()
    with owner("one"), pdb.connect_closing() as store:
        assert pdb.get_project(store, project_id).description == "desc\x00"
        assert pdb.get_active_id(store) == project_id
        import subprocess
        import sys
        code = r'''
import sys, sqlite3
def reject(*args, **kwargs):
    raise AssertionError('SQLite connection in PG Projects child')
sqlite3.connect = reject
from hermes_cli import projects_db as pdb
with pdb.connect_closing(profile_home=sys.argv[1]) as store:
    assert pdb.get_project(store, 'same').description == 'desc\x00'
    assert pdb.get_active_id(store) == 'p_same-id'
    pdb.update_project(store, 'p_same-id', color='from-child')
'''
        result = subprocess.run([sys.executable, "-c", code, str(home)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert pdb.get_project(store, project_id).color == "from-child"
        assert pdb.delete_project(store, project_id)
        assert pdb.get_project(store, project_id) is None


def test_concurrent_creation_and_primary_folder(project_profiles, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from hermes_cli import projects_db as pdb

    owner = project_profiles
    with owner("one"):
        def create(index):
            with pdb.connect_closing() as store:
                return pdb.create_project(store, name="same", folders=[str(tmp_path / str(index))])
        with ThreadPoolExecutor(max_workers=2) as workers:
            ids = [future.result() for future in [workers.submit(copy_context().run, create, index) for index in range(2)]]
        with pdb.connect_closing() as store:
            assert {project.slug for project in pdb.list_projects(store)} == {"same", "same-2"}
            other = str(tmp_path / "extra")
            pdb.add_folder(store, ids[0], other)
        def change(path):
            with pdb.connect_closing() as store:
                assert pdb.set_primary(store, ids[0], path)
        with ThreadPoolExecutor(max_workers=2) as workers:
            for future in [workers.submit(copy_context().run, change, path) for path in (str(tmp_path / "0"), other) * 4]:
                future.result()
        with pdb.connect_closing() as store:
            project = pdb.get_project(store, ids[0])
            assert [folder.path for folder in project.folders if folder.is_primary] == [project.primary_path]
            with pytest.raises(ValueError, match="already belongs"):
                pdb.create_project(store, name="duplicate", folders=[project.primary_path])


def test_real_tool_cli_web_and_tui_project_operations(project_profiles, capsys):
    from argparse import Namespace
    from hermes_cli.projects_cmd import projects_command
    from hermes_cli.web_routers.chat_workspaces import _collect_workspaces
    from tools.project_tools import registry
    from tui_gateway import server

    owner = project_profiles
    with owner("one"):
        result = json.loads(registry.dispatch("desktop_project", {"action": "create", "name": "Tool Project"}))
        assert result["success"]
        listing = json.loads(registry.dispatch("desktop_project", {"action": "list"}))
        assert listing["projects"][0]["name"] == "Tool Project"
        response = server._methods["projects.list"](1, {})
        assert "error" not in response, response
        assert response["result"]["projects"][0]["name"] == "Tool Project"
        response = server._methods["projects.create"](2, {"name": "RPC Project", "use": True})
        assert "error" not in response, response
        assert response["result"]["project"]["name"] == "RPC Project"
        assert projects_command(Namespace(project_action="list", include_archived=True)) == 0
        captured = capsys.readouterr()
        assert "Tool Project" in captured.out + captured.err
        assert {project["name"] for project in _collect_workspaces(None, False)["projects"]} == {"Tool Project", "RPC Project"}


def test_discovery_and_inventory_do_not_hide_pg_failure(project_profiles):
    from sqlalchemy import text
    from gateway.session_local_inventory import _project
    from hermes_cli import projects_db as pdb
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageError
    from tui_gateway import server

    with project_profiles("one"), pdb.connect_closing() as store:
        config, _scope = resolve_db_configuration()
        with get_engine(config.postgresql).begin() as conn:
            quoted = conn.dialect.identifier_preparer.quote(config.postgresql.schema)
            conn.execute(text(f"DROP TABLE {quoted}.discovered_repos"))
        with pytest.raises(StorageError):
            server._discover_repos_payload(None, conn=store)
        with pytest.raises(StorageError):
            _project("some/workspace")
