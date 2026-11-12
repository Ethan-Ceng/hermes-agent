"""Storage-owned scope binds preserve turn identity, frozen policy and captured secrets."""
from agent.runtime_scope import bind_profile_scope, bind_turn
from agent.secret_scope import get_secret
from hermes_cli.db_scope import OwnedProfileContext, bind_profile_home
from hermes_db.scope import DatabaseScope
from hermes_scope import Fence, current_scope, current_state


def test_nested_storage_bind_keeps_turn_fence_and_terminal_policy(tmp_path):
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    with bind_profile_scope(tmp_path), bind_turn("session", "turn", Fence(1, 2)):
        before = current_scope()
        policy = current_state().terminal
        with bind_profile_home(DatabaseScope(tmp_path)):
            assert current_scope() is before
            assert current_state().terminal is policy
        assert current_scope() is before


def test_captured_storage_owner_never_borrows_another_profiles_secrets(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for home, value in ((first, "alpha"), (second, "beta")):
        home.mkdir()
        (home / "config.yaml").write_text("{}", encoding="utf-8")
        (home / ".env").write_text("TEST_STORAGE_SENTINEL=" + value, encoding="utf-8")
    with bind_profile_scope(second):
        owner = OwnedProfileContext(DatabaseScope(second))
    (second / ".env").write_text("TEST_STORAGE_SENTINEL=changed", encoding="utf-8")
    with bind_profile_scope(first):
        outer = current_scope()
        with owner.activate():
            assert current_scope().agent == str(second)
            assert get_secret("TEST_STORAGE_SENTINEL") == "beta"
        assert current_scope() is outer
        assert get_secret("TEST_STORAGE_SENTINEL") == "alpha"
