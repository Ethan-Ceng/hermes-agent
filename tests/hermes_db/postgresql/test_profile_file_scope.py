"""Profile lifecycle keeps PG-owned local content reachable under its stable store_id."""

from copy import deepcopy
from pathlib import Path
import pytest
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace
from hermes_cli.db_setup import _owning_profile

from tests.hermes_cli.test_profiles import profile_env

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture(name="rename_home")
def _rename_home(pg_profiles, request, monkeypatch):
    from hermes_cli import profiles
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    root = request.getfixturevalue("profile_env") / ".hermes"
    source = root / "profiles" / "before"
    source.mkdir(parents=True)
    with pg_profiles("one") as example:
        config = read_user_config_raw(example / "config.yaml")
        atomic_config_write(source / "config.yaml", config)
        (source / ".env").write_bytes((example / ".env").read_bytes())
        master = deepcopy(config)
        master["storage"]["postgresql"]["store_id"] = "root"
        atomic_config_write(root / "config.yaml", master)
        (root / ".env").write_bytes((example / ".env").read_bytes())
    for name, result in (("_check_gateway_running", False), ("_cleanup_gateway_service", False),
                         ("_live_default_multiplexer", None), ("_stop_bot_desktop", None),
                         ("_maybe_register_gateway_service", None), ("_maybe_unregister_gateway_service", None)):
        monkeypatch.setattr(profiles, name, lambda *args, _result=result, **kwargs: _result)
    return source


def _content(source):
    with _owning_profile(source), kbc.connect_closing() as board:
        task = kb.create_task(board, title="rename content", workspace_kind="scratch")
        path = kb.workspaces_root() / task
        path.mkdir(parents=True)
        (path / "work.txt").write_bytes(b"workspace")
        workspace.set_workspace_path(board, task, path)
        attachment_id = kb.store_attachment_bytes(board, task, "proof.txt", b"persistent attachment")
    return task, path, attachment_id


def _assert_content(source, renamed, content):
    task, path, attachment_id = content
    with _owning_profile(renamed), kbc.connect_closing() as board:
        expected = renamed / path.relative_to(source)
        assert kb.get_task(board, task).workspace_path == str(expected)
        assert (expected / "work.txt").read_bytes() == b"workspace"
        attachment = kb.get_attachment(board, attachment_id)
        assert Path(attachment.stored_path).is_relative_to(renamed)
        assert Path(attachment.stored_path).read_bytes() == b"persistent attachment"
    assert not (renamed / "state.db").exists()


def test_profile_rename_reanchors_pg_workspace_and_attachment_paths(rename_home):
    from hermes_cli.profiles import rename_profile
    content = _content(rename_home)
    renamed = rename_profile("before", "after")
    _assert_content(rename_home, renamed, content)


@pytest.mark.parametrize("interruption", ["before_sql", "commit_unknown", "marker"])
def test_profile_move_resumes_without_publishing_partial_paths(rename_home, monkeypatch, interruption):
    from hermes_cli import profile_file_moves as moves, profiles
    from hermes_constants import named_profile_is_live
    from hermes_db.errors import UnknownCommitError, StorageUnavailableError
    source = rename_home
    target = source.with_name("after")
    content = _content(source)
    original = moves._reanchor_database

    def interrupted(*args):
        if interruption == "commit_unknown":
            original(*args)
            raise UnknownCommitError("test lost commit confirmation")
        raise StorageUnavailableError("test database unavailable")

    with monkeypatch.context() as patch:
        if interruption == "marker":
            patch.setattr(moves, "_replace_marker", lambda *args: (_ for _ in ()).throw(OSError("test marker interruption")))
        else:
            patch.setattr(moves, "_reanchor_database", interrupted)
        with pytest.raises((UnknownCommitError, StorageUnavailableError, OSError)):
            profiles.rename_profile("before", "after")
    assert not source.exists() and target.is_dir()
    assert not named_profile_is_live(target)
    assert moves.pending_move(source, target)
    assert profiles.rename_profile("before", "after") == target
    assert named_profile_is_live(target) and not moves.pending_move(source, target)
    _assert_content(source, target, content)


def test_profile_move_refuses_retarget_then_resumes_its_original_dataset(rename_home, monkeypatch):
    from hermes_cli import profile_file_moves as moves, profiles
    from hermes_cli.config import read_user_config_raw
    from hermes_constants import named_profile_is_live
    from hermes_db.errors import StorageConfigurationError, StorageUnavailableError
    from hermes_yaml import safe_dump
    source = rename_home
    target = source.with_name("after")
    content = _content(source)
    with monkeypatch.context() as patch:
        patch.setattr(moves, "_reanchor_database", lambda *args: (_ for _ in ()).throw(StorageUnavailableError("test offline")))
        with pytest.raises(StorageUnavailableError):
            profiles.rename_profile("before", "after")
    original = read_user_config_raw(target / "config.yaml")
    changed = deepcopy(original)
    changed["storage"]["postgresql"]["store_id"] = "unrelated"
    # Simulate an operator editing the existing file while the Profile is unpublished.
    (target / "config.yaml").write_text(safe_dump(changed), encoding="utf-8")
    with pytest.raises(StorageConfigurationError, match="identity changed"):
        profiles.rename_profile("before", "after")
    assert not named_profile_is_live(target) and moves.pending_move(source, target)
    (target / "config.yaml").write_text(safe_dump(original), encoding="utf-8")
    profiles.rename_profile("before", "after")
    _assert_content(source, target, content)


def test_rename_preserves_cleanup_fence_and_replays_under_new_home(rename_home, monkeypatch):
    from hermes_cli.profiles import rename_profile
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_cli.db_maintenance import maintain_profile
    from hermes_db.errors import StorageBusyError
    source = rename_home
    task, path, _attachment_id = _content(source)
    with _owning_profile(source), kbc.connect_closing() as board:
        with board.write() as conn:
            repo.task_update(conn, board, task, status="done")
        with monkeypatch.context() as patch:
            patch.setattr(workspace.shutil, "rmtree", lambda *args: (_ for _ in ()).throw(OSError("test interrupted cleanup")))
            kb._cleanup_workspace(board, task)
    renamed = rename_profile("before", "after")
    moved = renamed / path.relative_to(source)
    with _owning_profile(renamed), kbc.connect_closing() as board:
        other = kb.create_task(board, title="new reference")
        with pytest.raises(StorageBusyError):
            workspace.set_workspace_path(board, other, moved)
        assert moved.is_dir()
        maintain_profile(renamed)
        assert not moved.exists()
        workspace.set_workspace_path(board, other, moved)
        assert kb.get_task(board, other).workspace_path == str(moved)


def test_rename_only_reanchors_its_own_store(rename_home, pg_profiles):
    from hermes_cli.profiles import rename_profile
    source = rename_home
    content = _content(source)
    with pg_profiles("two") as peer:
        with kbc.connect_closing() as board:
            other = kb.create_task(board, title="independent pointer", workspace_kind="dir", workspace_path=str(content[1]))
    renamed = rename_profile("before", "after")
    _assert_content(source, renamed, content)
    with _owning_profile(peer), kbc.connect_closing() as board:
        assert kb.get_task(board, other).workspace_path == str(content[1])
