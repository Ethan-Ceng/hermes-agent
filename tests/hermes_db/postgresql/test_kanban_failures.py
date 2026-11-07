"""Attempt-scoped failure budgets never charge infrastructure or a successor."""

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_failure_budget_and_old_attempt_guard(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="failure", workspace_kind="scratch", max_retries=2)
        first = kb.claim_task(store, tid)
        assert not kb._record_task_failure(store, tid, "first", outcome="spawn_failed", release_claim=True,
            end_run=True, expected_run_id=first.current_run_id)
        assert kb.get_task(store, tid).consecutive_failures == 1
        second = kb.claim_task(store, tid)
        assert not kb._record_task_failure(store, tid, "late", outcome="spawn_failed", release_claim=True,
            end_run=True, expected_run_id=first.current_run_id)
        assert kb.get_task(store, tid).current_run_id == second.current_run_id
        assert kb._record_task_failure(store, tid, "second", outcome="spawn_failed", release_claim=True,
            end_run=True, expected_run_id=second.current_run_id)
        assert kb.get_task(store, tid).status == "blocked"
        assert kb.get_task(store, tid).consecutive_failures == 2
        assert kb.get_run(store, first.current_run_id).outcome == "spawn_failed"
        assert kb.get_run(store, second.current_run_id).outcome == "gave_up"


def test_infrastructure_attempts_preserve_budget_and_review_phase(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="review", assignee="coder", workspace_kind="scratch")
        assert kb.request_review(store, tid, summary="proof", reviewer="reviewer")
        for _ in range(3):
            run = kb.claim_review_task(store, tid)
            assert not kb._record_task_failure(store, tid, "host unavailable", outcome="spawn_failed",
                release_claim=True, end_run=True, infrastructure=True, force_trip=True, expected_run_id=run.current_run_id)
            assert kb.get_task(store, tid).status == "review"
            assert kb.get_task(store, tid).consecutive_failures == 0
            assert kb.get_run(store, run.current_run_id).metadata["infrastructure"] is True
        run = kb.claim_review_task(store, tid)
        assert kb._record_task_failure(store, tid, "protocol", outcome="crashed", release_claim=True,
            end_run=True, force_trip=True, expected_run_id=run.current_run_id)
        assert kb.recompute_ready(store, failure_limit=100) == 0
        assert kb.unblock_task(store, tid)
        assert kb.get_task(store, tid).status == "review"
