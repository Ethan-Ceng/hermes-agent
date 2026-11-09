"""Board recovery uses the real scoped PG admission ledger and current-run evidence."""

from contextlib import closing

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_owner_recovery as recovery
from hermes_db.access import open_session_store
from hermes_db.integration.runtime_access import runtime_for_store

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_owner_receipt_reads_real_admission_and_only_current_attempt(pg_profiles, monkeypatch):
    with pg_profiles("one") as home, kbc.connect_closing() as store, closing(open_session_store(home / "state.db")) as db:
        task_id = kb.create_task(store, title="managed", workspace_kind="scratch")
        first = kb.claim_task(store, task_id, claimer=kb._host_prefix() + "owner")
        assert not recovery.owner_reclaim_paused(store, task_id)
        db.create_session("owner", "kanban")
        runtime = runtime_for_store(db)
        epoch = runtime.begin_epoch(instance_id="owner")
        runtime.admit_input(epoch=epoch, principal_id="producer", session_id="owner", request_id="attempt", payload={})
        receipt = dict(storage_backend="postgresql", profile_home=str(home), store_id=db.scope.store_id,
                       principal_id="producer", session_id="owner", request_id="attempt")
        from hermes_db.integration.transfer.move_values import resource_key
        receipt["target"] = resource_key(db._transactions)
        kb._append_event(store, task_id, "owner_admitted", receipt, run_id=first.current_run_id)
        assert recovery.owner_reclaim_paused(store, task_id)
        admission = runtime.claim_input(epoch=epoch, session_id="owner")
        monkeypatch.setattr(recovery.psutil, "Process", lambda *args: pytest.fail("remote owner PID inferred"))
        assert recovery.owner_reclaim_paused(store, task_id)
        assert not recovery.owner_attempt_provably_over(store, task_id)
        runtime.settle_input(epoch=epoch, admission_id=admission["admission_id"], generation=admission["generation"],
                             outcome="completed")
        assert not recovery.owner_reclaim_paused(store, task_id)
        assert recovery.owner_attempt_note(store, task_id) == "owner admission settled completed"
        kb._append_event(store, task_id, "worker_bound", {"pid": 123, "claim_lock": first.claim_lock},
                         run_id=first.current_run_id)
        kb._append_event(store, task_id, "worker_result", {"pid": 123, "claim_lock": first.claim_lock, "exit_code": 0},
                         run_id=first.current_run_id)
        assert recovery.managed_run_exit_code(store, task_id, 456, first.claim_lock) == 0
        assert recovery.managed_run_exit_code(store, task_id, 456, "other") is None
        assert kb.block_task(store, task_id, reason="retry")
        assert kb.unblock_task(store, task_id)
        second = kb.claim_task(store, task_id, claimer=kb._host_prefix() + "next")
        assert second.current_run_id != first.current_run_id
        assert recovery._owner_receipt(store, task_id) is None
        assert recovery.managed_run_exit_code(store, task_id, 123, first.claim_lock) is None


def test_same_task_owner_evidence_never_crosses_board_or_store(pg_profiles, monkeypatch):
    monkeypatch.setattr(kb, "_new_task_id", lambda: "t_same")
    with pg_profiles("one"):
        kb.create_board("other")
        with kbc.connect_closing() as store:
            task_id = kb.create_task(store, title="one", workspace_kind="scratch")
            task = kb.claim_task(store, task_id)
            kb._append_event(store, task_id, "owner_admitted", {}, run_id=task.current_run_id)
            assert recovery.owner_reclaim_paused(store, task_id)
        with kbc.connect_closing(board="other") as store:
            kb.create_task(store, title="other", workspace_kind="scratch")
            kb.claim_task(store, task_id)
            assert not recovery.owner_reclaim_paused(store, task_id)
    with pg_profiles("two"), kbc.connect_closing() as store:
        kb.create_task(store, title="two", workspace_kind="scratch")
        kb.claim_task(store, task_id)
        assert not recovery.owner_reclaim_paused(store, task_id)


def test_pg_board_legacy_path_receipt_remains_ambiguous_without_opening_sqlite(pg_profiles):
    with pg_profiles("one") as home, kbc.connect_closing() as store:
        task_id = kb.create_task(store, title="untyped receipt", workspace_kind="scratch")
        task = kb.claim_task(store, task_id)
        kb._append_event(store, task_id, "owner_admitted", {"db": str(home / "legacy.db"),
            "session_id": "legacy", "request_id": "legacy"}, run_id=task.current_run_id)
        assert recovery.owner_reclaim_paused(store, task_id)
        from hermes_db.domains.kanban.postgres.evidence import snapshot
        with store.read() as conn:
            evidence = snapshot(conn, store, task_id)
        assert recovery.owner_reclaim_paused(evidence, task_id)


def test_owner_admission_receipt_refuses_same_ids_from_a_retargeted_schema(pg_profiles, postgres_engine, postgres_test_config):
    from copy import deepcopy
    from dataclasses import replace
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_db.integration.transfer.move_values import resource_key
    from hermes_db.schema import upgrade_schema
    from tests.hermes_db.pg_support import isolated_namespace
    with isolated_namespace(postgres_engine, postgres_test_config) as other_schema:
        upgrade_schema(replace(postgres_test_config.settings, schema=other_schema))
        with pg_profiles("one") as home:
            original = read_user_config_raw(home / "config.yaml")
            with closing(open_session_store(home / "state.db")) as db:
                db.create_session("same", "kanban")
                runtime = runtime_for_store(db)
                epoch = runtime.begin_epoch(instance_id="original")
                runtime.admit_input(epoch=epoch, principal_id="producer", session_id="same", request_id="same", payload={})
                receipt = dict(storage_backend="postgresql", profile_home=str(home), store_id=db.scope.store_id,
                    target=resource_key(db._transactions), principal_id="producer", session_id="same", request_id="same")
            changed = deepcopy(original)
            changed["storage"]["postgresql"]["schema"] = other_schema
            atomic_config_write(home / "config.yaml", changed)
            try:
                with closing(open_session_store(home / "state.db")) as db:
                    db.create_session("same", "kanban")
                    runtime = runtime_for_store(db)
                    epoch = runtime.begin_epoch(instance_id="different")
                    runtime.admit_input(epoch=epoch, principal_id="producer", session_id="same", request_id="same", payload={})
                    admission = runtime.claim_input(epoch=epoch, session_id="same")
                    runtime.settle_input(epoch=epoch, admission_id=admission["admission_id"], generation=admission["generation"], outcome="completed")
                assert recovery._admission_row(receipt) is None
            finally:
                atomic_config_write(home / "config.yaml", original)
            assert recovery._admission_row(receipt) == ("queued", None)


def test_pg_receipt_backend_change_stays_unknown_without_opening_legacy_sqlite(pg_profiles):
    from hermes_cli.config_backend import write_config_key
    with pg_profiles("one") as home:
        receipt = dict(storage_backend="postgresql", profile_home=str(home), store_id="one", target="captured",
            principal_id="producer", session_id="same", request_id="same")
        write_config_key(home / "config.yaml", "storage.backend", "sqlite")
        (home / "state.db").write_bytes(b"inactive bytes must not become an owner admission ledger")
        assert recovery._admission_row(receipt) is None
