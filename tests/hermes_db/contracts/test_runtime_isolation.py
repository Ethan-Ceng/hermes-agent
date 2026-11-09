"""Scoped queue, execution-lineage exclusion and atomic Core effects."""

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_same_schema_runtime_identity_and_epoch_are_scoped(core_pair):
    from hermes_db.integration.runtime_composition import create_runtime_store

    runtimes = [create_runtime_store(store) for store in core_pair]
    for store in core_pair:
        store.create_session("s", "test")
    epochs = [runtime.begin_epoch(instance_id="owner") for runtime in runtimes]
    args = dict(epoch=1, principal_id="human", session_id="s", request_id="r", payload={"text": "ask"})
    rows = [runtime.admit_input(**args) for runtime in runtimes]
    assert epochs == [1, 1] and rows[0]["admission_id"] != rows[1]["admission_id"]
    assert runtimes[0].get_admission(admission_id=rows[1]["admission_id"]) is None
    runtimes[0].begin_epoch(instance_id="replacement")
    assert runtimes[1].claim_input(epoch=1, session_id="s")["admission_id"] == rows[1]["admission_id"]
    with pytest.raises(RuntimeStoreError) as error:
        runtimes[0].claim_input(epoch=1, session_id="s")
    assert error.value.reason == "stale_epoch"


def test_worker_on_compression_child_blocks_logical_parent_but_not_branch(core_pair):
    from hermes_db.integration.runtime_composition import create_runtime_store
    from hermes_db.tables.runtime import worker_executions

    store = core_pair[0]
    runtime = create_runtime_store(store)
    store.create_session("s", "test")
    store.end_session("s", "compression")
    store.create_session("c", "test", parent_session_id="s")
    store.create_session("b", "test", parent_session_id="s", model_config={"_branched_from": "s"})
    epoch = runtime.begin_epoch(instance_id="owner")
    with store._write() as conn:
        conn.execute(worker_executions.insert().values(store_id=store.scope.store_id, execution_id="worker", session_id="c",
            kind="compute", status="running", adoption_digest="test-digest", owner_epoch=epoch, generation=1))
    for target in ("s", "b"):
        runtime.admit_input(epoch=epoch, principal_id="human", session_id=target, request_id="r", payload={"text": "ask"})
    assert runtime.claim_input(epoch=epoch, session_id="s") is None
    assert runtime.claim_input(epoch=epoch, session_id="b")["status"] == "started"


def test_core_effect_refusal_rolls_back_and_replay_bypasses_new_write_guard(core_pair):
    from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
    from hermes_db.domains.runtime.postgres.queries import runtime as repo
    from hermes_db.integration.runtime_composition import create_runtime_store

    store = core_pair[0]
    runtime = create_runtime_store(store)
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="owner")
    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={"text": "ask"})

    def refuse(conn, scope, *unused):
        repo.set_meta(conn, scope, "proof", "value")
        raise RuntimeStoreError("permission_denied")

    with pytest.raises(TypeError, match="CoreEffect"):
        runtime.admit_input(**args, _authorize_write=lambda conn: None)
    with pytest.raises(RuntimeStoreError):
        runtime.admit_input(**args, _authorize_write=CoreEffect(refuse))
    assert runtime.list_admissions(session_id="s") == []
    with store._read() as conn:
        assert repo.meta(conn, store.scope, "proof") is None
    row = runtime.admit_input(**args)
    assert runtime.admit_input(**args, _authorize_write=CoreEffect(refuse)) == row
    runtime.claim_input(epoch=epoch, session_id="s")
    with pytest.raises(RuntimeStoreError):
        runtime.settle_input(epoch=epoch, admission_id=row["admission_id"], generation=1, outcome="completed",
                              _terminal_write=CoreEffect(refuse))
    assert runtime.get_admission(admission_id=row["admission_id"])["status"] == "started"
    with store._read() as conn:
        assert repo.meta(conn, store.scope, "proof") is None


def test_claim_mark_follows_local_reset_target_and_ignores_other_store(core_pair):
    import json
    from hermes_db.domains.runtime.postgres.queries import runtime as repo
    from hermes_db.integration.runtime_composition import create_runtime_store
    from hermes_state_keys import local_identity
    from hermes_state_local import POLICY_PREFIX

    store, foreign = core_pair
    runtime = create_runtime_store(store)
    root = local_identity("profile", "human", "creation")
    store.create_session(root, "local", chat_id=root)
    store.end_session(root, "session_reset")
    store.create_session("child", "local", parent_session_id=root, chat_id=root, model_config={"_reset_from": root})
    own_id = store.append_message("child", "user", "previous")
    receipt = {"session_id": root, "profile_id": "profile", "principal_id": "human", "request_id": "creation",
               "lineage": [root, "child"], "entry": {"session_id": "child"}}
    with store._write() as conn:
        repo.set_meta(conn, store.scope, POLICY_PREFIX + root, json.dumps(receipt))
    foreign.create_session("child", "local")
    assert foreign.append_message("child", "user", "foreign") > own_id
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.admit_input(epoch=epoch, principal_id="human", session_id=root, request_id="r", payload={"text": "new"})
    assert runtime.claim_input(epoch=epoch, session_id=root)["transcript_mark"] == own_id
