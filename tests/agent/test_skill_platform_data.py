"""Canonical skill platform filtering accepts platform data without changing the interpreter host."""
import sys
import pytest
from agent.skill_utils import skill_matches_platform_list


@pytest.mark.parametrize("platforms,current,expected", [
    (["linux"], "linux", True), (["windows"], "linux", False),
    (["windows"], "win32", True), (["macos"], "darwin", True),
    ([], "win32", True), ("linux", "linux", True),
])
def test_platform_filter_is_explicit_data(platforms, current, expected):
    host = sys.platform
    assert skill_matches_platform_list(platforms, current_platform=current) is expected
    assert sys.platform == host
