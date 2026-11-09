"""Fault boundaries and scope/identity cases of compression coordination."""

from copy import deepcopy

import pytest


def test_core_late_parent_backfill_keeps_lease_and_refuses_two_live_holders(core_pair):
    store, _ = core_pair
    store.create_session("root", "test")
    store.end_session("root", "compression")
    store.create_session("late", "test")
    assert store.try_acquire_session_turn_lease("late", "child-owner")
    store.create_session("late", "test", parent_session_id="root")
    assert not store.try_acquire_session_turn_lease("root", "competitor")
    assert store.refresh_session_turn_lease("late", "child-owner")
    store.release_session_turn_lease("root", "child-owner")
    assert store.try_acquire_session_turn_lease("root", "root-owner")
    store.create_session("conflict", "test")
    assert store.try_acquire_session_turn_lease("conflict", "different")
    from hermes_db.errors import StorageConflictError
    with pytest.raises(StorageConflictError):
        store.create_session("conflict", "test", parent_session_id="root")
    assert store.get_session("conflict")["parent_session_id"] is None


def test_core_archive_failure_rolls_back_rows_config_counters_and_physical_stamps(core_pair, monkeypatch):
    from hermes_db.domains.sessions.postgres.operations import messages

    store, _ = core_pair
    store.create_session("s", "test")
    store.append_message("s", "user", "original")
    before = store.get_session("s")
    batch = [{"role": "user", "content": "summary"}]
    insert = messages.insert_rows

    def fail_after_insert(*args, **kwargs):
        insert(*args, **kwargs)
        raise RuntimeError("injected after insertion")

    monkeypatch.setattr(messages, "insert_rows", fail_after_insert)
    with pytest.raises(RuntimeError, match="injected"):
        store.archive_and_compact("s", batch, model_config_patch={"must": "rollback"})
    assert store.get_session("s") == before
    assert [row["content"] for row in store.get_messages("s", include_inactive=True)] == ["original"]
    assert "_row_id" not in batch[0] and "timestamp" not in batch[0]


def test_core_worker_publication_origin_retry_and_scope_survive_new_handle(core_pair, tmp_path):
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore
    from hermes_db.integration.session_composition import create_session_store

    first, foreign = core_pair
    for store in core_pair:
        store.create_session("p", "test")
    runtime = PostgresRuntimeStore(first)
    epoch = runtime.begin_epoch(instance_id="owner")
    assignment = dict(epoch=epoch, execution_id="same", session_id="p", generation=0)
    runtime.register_worker(**assignment, kind="compute", adoption_secret="private")
    payload = dict(child_session_id="c", source="test", messages=[{"role": "user", "content": "handoff\x00"}],
        model=None, model_config=None, system_prompt="prompt\x00", cwd=None, profile_name=None,
        compression_lock_holder="holder", require_compression_lease=True, require_lease_refresh=False,
        lease_ttl_seconds=300, watermark=None, watermark_ceiling=None)
    assert first.try_acquire_compression_lock("p", "holder")
    params = dict(**assignment, sequence=1, operation="compression.publish", payload=payload)
    expected = runtime.mutate_worker(**params)
    reopened = create_session_store(first._transactions, first.scope)
    try:
        recovered = PostgresRuntimeStore(reopened)
        assert recovered.mutate_worker(**params) == expected
        assert recovered.worker_claim_origin(params | {"session_id": "c"}) == "p"
        assert recovered.worker_retry_target(params) == "c"
        assert PostgresRuntimeStore(foreign).worker_claim_origin(params | {"session_id": "foreign"}) == "foreign"
        assert reopened.get_compression_chain("p") == ["p", "c"]
    finally:
        reopened.close()


def test_rewritten_carried_tail_is_compacted_history_and_not_cloned(store):
    store.create_session("s", "test")
    mark = store.get_active_message_watermark("s")
    tail = [{"role": "user", "content": "durable current body"}]
    store.append_messages_batch("s", tail)
    rewritten = deepcopy(tail[0])
    rewritten["content"] = "summary header\ndurable current body\nend"
    rewritten["_compressed_summary"] = True
    assert store.archive_and_compact("s", [rewritten], watermark=mark) == 1
    rows = store.get_messages("s", include_inactive=True)
    assert len(rows) == 2 and rows[0]["compacted"] == 1 and rows[0]["active"] == 0
    assert rows[-1]["content"] == rewritten["content"]


def test_unaddressed_held_snapshot_rejects_rewritten_active_uid(store):
    from hermes_state_errors import HeldRowRewrittenError

    store.create_session("s", "test")
    held = [{"role": "user", "content": "old"}]
    store.append_messages_batch("s", held)
    row_id = held[0].pop("_row_id")
    held[0]["_db_persisted"] = True
    store.set_user_message_content("s", row_id, "new")
    with pytest.raises(HeldRowRewrittenError):
        store.archive_and_compact("s", [{"role": "user", "content": "summary"}], held_for_cas=held)
    assert store.get_messages("s")[0]["content"] == "new"


def test_core_local_route_and_receipt_advance_atomically_with_child(core_pair):
    import json
    from hermes_db.domains.runtime.postgres.queries import runtime
    from hermes_db.domains.sessions.postgres.queries.lineage import physical_target
    from hermes_db.tables.gateway import gateway_routing
    from hermes_state_keys import local_identity
    from hermes_state_local import POLICY_PREFIX
    from hermes_state_runtime import RuntimeStoreError

    store, _ = core_pair
    for conflicting in (False, True):
        request = "conflict" if conflicting else "success"
        root = local_identity("profile", "human", request)
        child, route = "child-" + request, "route-" + request
        store.create_session(root, "local", chat_id=root, user_id="human", session_key=route)
        receipt = dict(session_id=root, profile_id="profile", principal_id="human", request_id=request,
            route=route, entry={"session_id": root}, lineage=[root])
        with store._write() as conn:
            runtime.set_meta(conn, store.scope, POLICY_PREFIX + root, json.dumps(receipt))
            conn.execute(gateway_routing.insert().values(store_id=store.scope.require_store_id(), scope="", session_key=route,
                entry_json=json.dumps({"session_id": "moved" if conflicting else root}), updated_at=0))
        assert store.try_acquire_compression_lock(root, "holder")

        def publish():
            store.publish_compression_child(parent_session_id=root, child_session_id=child, source="local",
                messages=[{"role": "user", "content": "handoff"}], compression_lock_holder="holder")

        if conflicting:
            with pytest.raises(RuntimeStoreError) as error:
                publish()
            assert error.value.reason == "admission_conflict"
            assert store.get_session(child) is None and store.get_session(root)["ended_at"] is None
        else:
            publish()
            with store._read() as conn:
                assert physical_target(conn, store.scope, root) == child
                saved = json.loads(runtime.meta(conn, store.scope, POLICY_PREFIX + root))
                assert saved["lineage"] == [root, child] and saved["entry"]["session_id"] == child
