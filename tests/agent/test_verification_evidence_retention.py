"""Retention must preserve a full-workspace proof referenced by another session."""

from agent import verification_evidence as ve


def test_session_cap_preserves_shared_current_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    monkeypatch.setattr(ve, "_MAX_EVENTS_PER_SESSION_ROOT", 3)
    ve.mark_workspace_edited(session_id="editor", cwd=tmp_path, paths=["a.py"])
    original = ve.record_verify_run(root=tmp_path, session_id="verifier", ok=True)
    for _ in range(5):
        ve.record_verify_run(root=tmp_path, session_id="verifier", ok=False, scope="targeted")
    result = ve.verification_status(session_id="editor", cwd=tmp_path)
    assert result["status"] == "passed"
    assert result["evidence"]["id"] == original["id"]
