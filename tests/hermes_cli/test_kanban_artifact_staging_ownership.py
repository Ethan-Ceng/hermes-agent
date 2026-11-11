"""A failed handoff only compensates files that handoff actually created."""

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace


@pytest.mark.parametrize("mode", ["existing_reference", "caller_marker"])
def test_review_rollback_retains_preexisting_attachment(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    kbc.init_db()
    with kbc.connect_closing() as store:
        tid = kb.create_task(store, title="proof", assignee="author", workspace_kind="scratch")
        path = kb.workspaces_root() / tid
        path.mkdir(parents=True)
        fresh = path / "fresh.txt"
        fresh.write_text("fresh", encoding="utf-8")
        workspace.set_workspace_path(store, tid, path)
        existing_id = kb.store_attachment_bytes(store, tid, "existing.txt", b"existing")
        existing = Path(kb.get_attachment(store, existing_id).stored_path)
        run = kb.claim_task(store, tid)
        append = kb._append_event
        def fail_handoff(conn, task_id, kind, *args, **kwargs):
            if kind == "review_requested":
                raise RuntimeError("handoff rolled back")
            return append(conn, task_id, kind, *args, **kwargs)
        monkeypatch.setattr(kb, "_append_event", fail_handoff)
        metadata = ({"artifacts": [str(existing), str(fresh)]} if mode == "existing_reference"
                    else {"artifacts": [], "_staged_artifacts": [str(existing)]})
        with pytest.raises(RuntimeError, match="handoff rolled back"):
            kb.request_review(store, tid, summary="proof", reviewer="reviewer", expected_run_id=run.current_run_id,
                              metadata=metadata)
        assert existing.read_bytes() == b"existing"
        assert fresh.read_text(encoding="utf-8") == "fresh"
        assert [attachment.id for attachment in kb.list_attachments(store, tid)] == [existing_id]
        assert kb.get_task(store, tid).status == "running"
