"""Worktree lifetime follows a captured PG Profile, including persisted Git lock reasons."""

import pytest
from tests.hermes_cli.test_tui_worktree_clean_quit import _repo

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_real_git_retention_marker_reopens_owning_pg_store_under_other_profile(pg_profiles, tmp_path, monkeypatch):
    from hermes_cli.db_setup import open_profile_db
    from hermes_cli.worktree_storage import capture_worktree_store
    from hermes_cli.worktree_ops import _setup_worktree, _retain_worktree_for_session, _worktree_lock_is_live, _worktree_lock_reason
    with pg_profiles("one") as home:
        repo = _repo(tmp_path)
        monkeypatch.chdir(repo)
        reference = capture_worktree_store()
        info = _setup_worktree(str(repo), sync_base=False, retain_db=reference)
        with open_profile_db(home) as handle:
            handle.sessions.create_session("worktree-owned", "tui", cwd=info["path"])
            handle.sessions.append_message("worktree-owned", "user", "resumable history")
            handle.sessions.end_session("worktree-owned", "tui_shutdown")
        assert _retain_worktree_for_session(str(repo), info["path"], "worktree-owned", reference)
        found, reason = _worktree_lock_reason(str(repo), info["path"], 10)
        assert found and " store=" in reason and " db=" not in reason
        assert not (home / "state.db").exists()
    with pg_profiles("two"):
        assert _worktree_lock_is_live(str(repo), info["path"]) == "live"


def test_pg_worktree_observations_keep_active_goal_and_reject_scope_change(pg_profiles, tmp_path):
    from hermes_cli.db_setup import open_profile_db
    from hermes_cli.worktree_storage import capture_worktree_store
    from hermes_cli.worktree_ops import _retained_tree_is_live, _tree_still_served
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.domains.runtime.postgres.queries.runtime import set_meta
    import hermes_yaml as yaml
    from hermes_cli.config import atomic_config_write
    tree = tmp_path / "tree"
    tree.mkdir()
    with pg_profiles("one") as home:
        reference = capture_worktree_store()
        with open_profile_db(home) as handle:
            handle.sessions.create_session("goal-owner", "tui", cwd=str(tree))
            handle.sessions.end_session("goal-owner", "tui_shutdown")
        assert not _retained_tree_is_live(reference, str(tree))
        assert _tree_still_served(reference, str(tree)) is None
        with acquire_profile_domain("sessions", profile_home=home) as resource, resource.write() as conn:
            set_meta(conn, resource.scope, "goal:goal-owner", '{"status":"active"}')
        assert _tree_still_served(reference, str(tree)) == "session"
        config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
        config["storage"]["postgresql"]["store_id"] = "different-store"
        atomic_config_write(home / "config.yaml", config)
        assert _retained_tree_is_live(reference, str(tree))
        assert _tree_still_served(reference, str(tree)) == "unreadable"
