"""SSH path syntax belongs to the target shell, independently of the control host."""
import pytest

from tui_gateway.server import _is_remote_cwd_shape


@pytest.mark.parametrize("raw, expected", [
    ("/", True), ("/home/project", True), ("~", True), ("~/project", True),
    ("relative/project", False), ("", False),
])
def test_target_absolute_and_tilde_paths_are_accepted(raw, expected):
    assert _is_remote_cwd_shape(raw) is expected


def test_control_host_absolute_paths_keep_their_existing_contract(tmp_path):
    assert _is_remote_cwd_shape(str(tmp_path)) is True
