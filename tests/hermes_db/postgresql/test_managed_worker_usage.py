"""The real PG managed-worker settlement follows compression without SQLite row methods."""

from types import SimpleNamespace

import pytest

from gateway.session_managed_worker import _settled_session_usage

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_finished_pg_worker_usage_does_not_turn_success_into_unknown(pg_store):
    pg_store.create_session("root", "kanban")
    pg_store.update_token_counts("root", input_tokens=10, output_tokens=5, api_call_count=1)
    usage = _settled_session_usage(SimpleNamespace(db=pg_store), "root", {"model": "m"})["session_usage"]
    assert usage["total_tokens"] == 15 and usage["api_calls"] == 1


def test_pg_worker_usage_excludes_branch_origin_and_stale_siblings(pg_store, pg_runtime):
    pg_store.create_session("origin", "cli")
    pg_store.update_token_counts("origin", input_tokens=9000, output_tokens=900)
    pg_store.create_session("branch", "kanban", parent_session_id="origin", model_config={"_branched_from": "origin"})
    pg_store.update_token_counts("branch", input_tokens=200, output_tokens=50, api_call_count=2)
    pg_store.end_session("branch", "compression")
    pg_store.create_session("tip", "kanban", parent_session_id="branch", model_config={"_branched_from": "origin"})
    pg_store.update_token_counts("tip", input_tokens=300, output_tokens=70, cache_read_tokens=100, api_call_count=1)
    pg_store.create_session("stale", "kanban", parent_session_id="branch")
    pg_store.update_token_counts("stale", input_tokens=7000, output_tokens=700)
    epoch = pg_runtime.begin_epoch(instance_id="owner")
    pg_runtime.register_worker(epoch=epoch, execution_id="worker", session_id="tip", generation=0,
                               kind="compute", adoption_secret="fixture-secret")
    usage = _settled_session_usage(SimpleNamespace(db=pg_store), "branch", {"model": "m"}, "worker")["session_usage"]
    assert (usage["input_tokens"], usage["output_tokens"], usage["cache_read_tokens"], usage["api_calls"]) == (500, 120, 100, 3)
