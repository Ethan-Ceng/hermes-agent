"""Atomic dispatchable swarm topology and real CLI diagnostics on PostgreSQL."""

import json
import time
import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_swarm as swarm

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def build(store):
    return swarm.create_swarm(store, goal="durable swarm🙂", workers=[
        swarm.SwarmWorkerSpec("default", "worker", "work")], verifier_assignee="default",
        synthesizer_assignee="default", idempotency_key="same-swarm")


def test_swarm_is_dispatchable_idempotent_and_survives_reopen(pg_profiles):
    from hermes_cli.kanban import run_slash
    from hermes_db.domains.kanban.postgres.queries import kanban as repo
    from hermes_db.tables.kanban import events
    from sqlalchemy import update
    with pg_profiles("one"):
        with kbc.connect_closing() as store:
            created = build(store)
            assert build(store) == created
            assert kb.get_task(store, created.root_id).status == "done"
            assert kb.latest_run(store, created.root_id).outcome == "completed"
            assert kb.get_task(store, created.worker_ids[0]).status == "ready"
            assert kb.get_task(store, created.verifier_id).status == "todo"
            assert kb.parent_ids(store, created.verifier_id) == created.worker_ids
            swarm.post_blackboard_update(store, created.root_id, author="worker", key="proof", value="🙂\x00")
            with store.write() as conn:
                conn.execute(update(events).where(repo.key(store, created.worker_ids[0], events))
                             .values(created_at=int(time.time()) - 7200))
        with kbc.connect_closing() as reopened:
            assert swarm.latest_blackboard(reopened, created.root_id)["proof"] == "🙂\x00"
            assert len(kb.list_tasks(reopened)) == 4
        output = json.loads(run_slash("diagnostics --json"))
        assert any(row.get("task_id") == created.worker_ids[0] for row in output)
    with pg_profiles("two"), kbc.connect_closing() as other:
        assert kb.list_tasks(other) == []


def test_swarm_failure_rolls_back_whole_graph_and_activation(pg_profiles, monkeypatch):
    from hermes_db.domains.kanban.postgres.operations import swarm as core
    with pg_profiles("one"), kbc.connect_closing() as writer, kbc.connect_closing() as observer:
        original = core.create.insert_prepared
        calls = []

        def fail(*args, **kwargs):
            result = original(*args, **kwargs)
            calls.append(result)
            assert kb.list_tasks(observer) == []
            if len(calls) == 3:
                raise RuntimeError("test interrupted topology")
            return result

        monkeypatch.setattr(core.create, "insert_prepared", fail)
        with pytest.raises(RuntimeError, match="interrupted topology"):
            build(writer)
        assert kb.list_tasks(writer) == []
        assert kb.list_tasks(observer) == []
