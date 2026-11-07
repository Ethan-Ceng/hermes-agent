"""Completion evidence, run fences and actual scratch artifact preservation."""

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_completion_requires_evidence_and_unblocks_child(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        parent = kb.create_task(store, title="parent", workspace_kind="scratch")
        child = kb.create_task(store, title="child", workspace_kind="scratch", parents=[parent])
        claim = kb.claim_task(store, parent)
        with pytest.raises(kb.EmptyCompletionError):
            kb.complete_task(store, parent, expected_run_id=claim.current_run_id)
        assert kb.get_task(store, parent).status == "running"
        assert any(event.kind == "completion_blocked_empty_result" for event in kb.list_events(store, parent))
        assert kb.complete_task(store, parent, result="proof\x00🙂", metadata={}, expected_run_id=claim.current_run_id)
        assert kb.get_task(store, parent).result == "proof\x00🙂"
        run = kb.get_run(store, claim.current_run_id)
        assert run.outcome == "completed" and run.summary == "proof\x00🙂" and run.metadata == {}
        assert kb.get_task(store, child).status == "ready"
        assert kb.goal_run_status(store, parent, run.id) == "done"


def test_late_completion_cannot_close_successor(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="fenced", workspace_kind="scratch")
        old = kb.claim_task(store, tid)
        assert kb.reclaim_task(store, tid)
        new = kb.claim_task(store, tid)
        assert not kb.complete_task(store, tid, result="late", expected_run_id=old.current_run_id)
        assert kb.get_task(store, tid).current_run_id == new.current_run_id
        assert kb.get_task(store, tid).result is None
        assert kb.complete_task(store, tid, result="current", expected_run_id=new.current_run_id)
        assert kb.get_run(store, old.current_run_id).outcome == "reclaimed"
        assert kb.get_run(store, new.current_run_id).outcome == "completed"


def test_declared_artifact_failure_preserves_run_then_success_is_durable(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="artifact", workspace_kind="scratch")
        path = kb.workspaces_root(board="default") / tid
        path.mkdir(parents=True)
        workspace.set_workspace_path(store, tid, path)
        claim = kb.claim_task(store, tid)
        proof = path / "proof.txt"
        with pytest.raises(kb.ArtifactPreservationError):
            kb.complete_task(store, tid, summary="proof", metadata={"artifacts": [str(proof)]}, expected_run_id=claim.current_run_id)
        assert kb.get_task(store, tid).status == "running"
        assert kb.list_attachments(store, tid) == []
        proof.write_text("durable proof", encoding="utf-8")
        assert kb.complete_task(store, tid, summary="proof", metadata={"artifacts": [str(proof)]}, expected_run_id=claim.current_run_id)
        assert not path.exists()
        attachment = kb.list_attachments(store, tid)[0]
        assert Path(attachment.stored_path).read_text(encoding="utf-8") == "durable proof"
        run = kb.get_run(store, claim.current_run_id)
        assert run.metadata["artifacts"] == [attachment.stored_path]


def test_completion_unknown_commit_retains_committed_artifact(pg_profiles, monkeypatch):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from hermes_db.errors import UnknownCommitError
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="uncertain completion", workspace_kind="scratch")
        path = kb.workspaces_root(board="default") / tid
        path.mkdir(parents=True)
        workspace.set_workspace_path(store, tid, path)
        proof = path / "proof.txt"
        proof.write_text("committed", encoding="utf-8")
        claim = kb.claim_task(store, tid)
        dialect = store._transactions.engine.dialect
        commit = dialect.do_commit
        def lose_ack(connection):
            commit(connection)
            raise OperationalError(None, None, psycopg.OperationalError("commit acknowledgement lost"))
        with monkeypatch.context() as failure:
            failure.setattr(dialect, "do_commit", lose_ack)
            with pytest.raises(UnknownCommitError):
                kb.complete_task(store, tid, summary="proof", metadata={"artifacts": [str(proof)]}, expected_run_id=claim.current_run_id)
        assert kb.get_task(store, tid).status == "done"
        attachment = kb.list_attachments(store, tid)[0]
        assert Path(attachment.stored_path).read_text(encoding="utf-8") == "committed"
        assert proof.read_text(encoding="utf-8") == "committed"


def test_pr_acceptance_runs_off_connection_and_keeps_assignee_identity(pg_profiles, monkeypatch):
    from hermes_cli import kanban_pr_acceptance as acceptance
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="PR", workspace_kind="scratch", assignee="coder", completion_contract="owner/repo")
        claim = kb.claim_task(store, tid)
        results = iter([False, True])
        def collect(contract, published_pr, assignee=None):
            assert assignee == "coder"
            assert contract == published_pr == "https://github.com/owner/repo/pull/1"
            assert store._transactions.engine.pool.checkedout() == 0
            return {"ok": next(results), "classification": "checks", "recovery": "rerun checks", "detail": "receipt"}
        monkeypatch.setattr(acceptance, "collect_acceptance", collect)
        metadata = {"published_pr": "https://github.com/owner/repo/pull/1"}
        assert not kb.complete_task(store, tid, summary="proof", metadata=metadata, expected_run_id=claim.current_run_id)
        assert kb.get_task(store, tid).status == "running"
        assert "PR acceptance checks" in kb.get_task(store, tid).last_failure_error
        assert kb.complete_task(store, tid, summary="proof", metadata=metadata, expected_run_id=claim.current_run_id)
        assert kb.get_task(store, tid).status == "done"


def test_completed_result_edit_updates_original_handoff(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="backfill", workspace_kind="scratch")
        assert not kb.edit_task(store, tid, result="too early")
        assert kb.complete_task(store, tid, result="first")
        run_id = kb.latest_run(store, tid).id
        metadata = {"zero": 0, "false": False, "empty": [], "null": None}
        assert kb.edit_task(store, tid, title="edited", result="revised\x00🙂", metadata=metadata)
        assert kb.get_task(store, tid).title == "edited"
        assert kb.get_task(store, tid).result == "revised\x00🙂"
        run = kb.get_run(store, run_id)
        assert run.summary == "revised\x00🙂" and run.metadata == metadata
        assert kb.latest_summaries(store, [tid]) == {tid: "revised\x00🙂"}
        assert len(kb.list_runs(store, tid)) == 1
