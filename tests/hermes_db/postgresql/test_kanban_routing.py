"""Manual promotion/reassignment preserve business refusals and storage errors."""

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_manual_promotion_and_reassignment_respect_parents_and_live_claims(pg_profiles):
    with pg_profiles("one"), kbc.connect_closing() as store:
        parent = kb.create_task(store, title="parent", workspace_kind="scratch")
        child = kb.create_task(store, title="child", workspace_kind="scratch", parents=[parent])
        ok, reason = kb.promote_task(store, child, actor="operator")
        assert not ok and "unsatisfied parent" in reason
        assert kb.unlink_tasks(store, parent, child)
        assert kb.block_task(store, child, kind="needs_input")
        assert kb.promote_task(store, child, actor="operator", dry_run=True) == (True, None)
        assert kb.get_task(store, child).status == "blocked"
        assert kb.promote_task(store, child, actor="operator") == (True, None)
        assert kb.assign_task(store, child, "first")
        run = kb.claim_task(store, child)
        assert not kb.reassign_task(store, child, "second")
        assert kb.reassign_task(store, child, "second", reclaim_first=True)
        assert kb.get_task(store, child).assignee == "second"
        assert kb.get_run(store, run.current_run_id).outcome == "reclaimed"


def test_reassignment_storage_failure_is_not_a_business_refusal(pg_profiles):
    from sqlalchemy import text
    from hermes_db.errors import StorageError
    with pg_profiles("one"), kbc.connect_closing() as store:
        tid = kb.create_task(store, title="unavailable", workspace_kind="scratch")
        with store.write() as conn:
            schema = conn.dialect.identifier_preparer.quote(store.settings.postgresql.schema)
            conn.execute(text(f"DROP TABLE {schema}.kanban_tasks CASCADE"))
        with pytest.raises(StorageError):
            kb.reassign_task(store, tid, "second")
