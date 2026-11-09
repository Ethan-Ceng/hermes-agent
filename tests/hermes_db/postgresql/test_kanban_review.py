"""Reviewer/implementer provenance survives handoffs and owner-store reopening."""

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_review_changes_and_rereview_restore_original_provenance(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="review", assignee="coder", workspace_kind="scratch")
        implementation = kb.claim_task(store, tid)
        assert kb.request_review(store, tid, reviewer="reviewer", summary="implemented", expected_run_id=implementation.current_run_id)
        assert kb.get_task(store, tid).assignee == "reviewer"
        assert kb.get_run(store, implementation.current_run_id).profile == "coder"
        review = kb.claim_review_task(store, tid)
        assert kb.request_changes(store, tid, reason="adjust", expected_run_id=review.current_run_id) == (True, "coder")
        assert kb.get_task(store, tid).status == "ready"
        assert kb.get_task(store, tid).assignee == "coder"
        retry = kb.claim_task(store, tid)
        assert not kb.request_review(store, tid, summary="stale", expected_run_id=implementation.current_run_id)
        assert kb.request_review(store, tid, summary="adjusted", expected_run_id=retry.current_run_id)
        assert kb.get_task(store, tid).assignee == "reviewer"
        assert kb.complete_task(store, tid)
        assert kb.get_task(store, tid).status == "done"
        assert kb.latest_summary(store, tid) == kb._REVIEW_APPROVED_NOTE


@pytest.mark.parametrize("failure_phase", ["body", "commit"])
def test_review_failure_compensates_only_new_artifacts(pg_profiles, monkeypatch, failure_phase):
    from hermes_db.domains.kanban.postgres import repository as repo
    from hermes_db.tables.kanban import events
    from hermes_db.errors import StorageConflictError
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="review artifact", assignee="coder", workspace_kind="scratch")
        path = kb.workspaces_root() / tid
        path.mkdir(parents=True)
        workspace.set_workspace_path(store, tid, path)
        fresh = path / "fresh.txt"
        fresh.write_text("fresh", encoding="utf-8")
        aid = kb.store_attachment_bytes(store, tid, "existing.txt", b"existing")
        existing = Path(kb.get_attachment(store, aid).stored_path)
        before_files = {item for item in kb.task_attachments_dir(tid).rglob("*") if item.is_file()}
        run = kb.claim_task(store, tid)
        event = repo.event
        def fail_review(conn, resource, task_id, kind, *args, **kwargs):
            if kind == "review_requested":
                if failure_phase == "body":
                    raise RuntimeError("review rollback")
                # The run FK is checked at COMMIT, after all staging and body writes succeeded.
                conn.execute(events.insert().values(**repo.owner(resource), task_id=task_id.encode(),
                    kind=b"invalid_receipt", run_id=999999999999, created_at=0))
            return event(conn, resource, task_id, kind, *args, **kwargs)
        with monkeypatch.context() as failure:
            failure.setattr(repo, "event", fail_review)
            expected = RuntimeError if failure_phase == "body" else StorageConflictError
            with pytest.raises(expected):
                kb.request_review(store, tid, reviewer="reviewer", summary="proof", expected_run_id=run.current_run_id,
                                  metadata={"artifacts": [str(existing), str(fresh)]})
        assert existing.read_bytes() == b"existing"
        assert fresh.read_text(encoding="utf-8") == "fresh"
        assert [attachment.id for attachment in kb.list_attachments(store, tid)] == [aid]
        assert kb.get_task(store, tid).status == "running"
        assert {item for item in kb.task_attachments_dir(tid).rglob("*") if item.is_file()} == before_files


def test_worker_context_reads_runs_comments_and_scoped_role_history(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        prior = kb.create_task(store, title="previous", assignee="coder", workspace_kind="scratch")
        assert kb.complete_task(store, prior, summary="previous proof")
        tid = kb.create_task(store, title="current", assignee="coder", workspace_kind="scratch", parents=[prior])
        kb.add_comment(store, tid, "author", "current comment")
        context = kb.build_worker_context(store, tid)
        assert "previous proof" in context
        assert "current comment" in context
        assert "Recent work by @coder" in context
