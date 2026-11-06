"""Managed-worker compression uses one receipt transaction and current identity."""

import time

import pytest

from hermes_state_runtime import RuntimeStoreError


def test_worker_rotation_lost_ack_replays_once_and_preserves_fifo(store, runtime, tmp_path):
    from agent.runtime_session_store import RuntimeSessionStore, apply_row_annotations

    store.create_session("root", "cli", system_prompt="PREFIX")
    epoch = runtime.begin_epoch(instance_id="owner")
    request = dict(epoch=epoch, principal_id="human", session_id="root", request_id="first", payload={"text": "first"})
    accepted = runtime.admit_input(**request)
    started = runtime.claim_input(epoch=epoch, session_id="root")
    follower = runtime.admit_input(**(request | {"request_id": "follower", "payload": {"text": "second"}}))
    scope = dict(epoch=epoch, execution_id="admission-worker:" + accepted["admission_id"], session_id="root",
                 generation=started["generation"])
    runtime.register_worker(**scope, kind="compute", adoption_secret="private")
    worker = RuntimeSessionStore(lambda method, **params: runtime.mutate_worker(**params), scope, tmp_path / "outbox")
    try:
        batch = [{"role": "user", "content": "keep\x00once"}]
        worker.append_messages_batch("root", batch)
        uid = batch[0]["message_uid"]
        for parent, child in (("root", "child"), ("child", "grandchild")):
            assert worker.try_acquire_compression_lock(parent, "holder")
            args = []

            def lost_ack(method, **params):
                args.append(params)
                runtime.mutate_worker(**params)
                raise TimeoutError("lost publication reply")

            worker.rpc = lost_ack
            with pytest.raises(TimeoutError):
                worker.publish_compression_child(parent_session_id=parent, child_session_id=child,
                    source="cli", messages=batch, system_prompt="PREFIX\x00", compression_lock_holder="holder")
            assert worker.scope["session_id"] == parent
            worker.rpc = lambda method, **params: runtime.mutate_worker(**params)
            replay = worker.retry_pending()[0]
            apply_row_annotations(batch, replay["annotations"])
            assert worker.scope["session_id"] == child
            assert batch[0]["message_uid"] == uid and store.get_messages(child)[0]["message_uid"] == uid
            assert runtime.claim_input(epoch=epoch, session_id="root") is None
            assert runtime.admit_input(**request)["admission_id"] == accepted["admission_id"]
            assert runtime.mutate_worker(**args[0])["worker_assignment"] == {"parent": parent, "session_id": child}
        assert runtime.get_admission(admission_id=follower["admission_id"])["status"] == "queued"
        worker.archive_and_compact("grandchild", batch)
        assert len(store.get_messages("grandchild")) == 1
        assert store.get_messages("grandchild")[0]["message_uid"] == uid
    finally:
        worker.failure = None
        worker.journal["pending"] = []
        worker.close()


def test_worker_compression_guards_and_lineage_reads_are_owned(store, runtime, tmp_path):
    from agent.runtime_session_store import RuntimeSessionStore

    store.create_session("owned", "cli")
    store.create_session("foreign", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    scope = dict(epoch=epoch, execution_id="worker", session_id="owned", generation=0)
    runtime.register_worker(**scope, kind="compute", adoption_secret="private")
    worker = RuntimeSessionStore(lambda method, **params: runtime.mutate_worker(**params), scope, tmp_path / "outbox")
    try:
        saved = worker.get_compression_failure_cooldown_row("owned")
        worker.record_compression_failure_cooldown("owned", time.time() + 500, "error\x00")
        assert worker.get_compression_failure_cooldown("owned")["error"] == "error\x00"
        worker.restore_compression_failure_cooldown_row("owned", saved)
        assert store.get_compression_failure_cooldown("owned") is None
        worker.set_compression_fallback_streak("owned", 3)
        assert store.get_compression_fallback_streak("owned") == 3
        batch = [{"role": "user", "content": "held"}]
        worker.append_messages_batch("owned", batch)
        assert worker.get_active_message_watermark("owned") == batch[0]["_row_id"]
        assert worker.get_compression_tip("owned") == "owned"
        assert worker.get_messages_as_conversation("owned")[0]["content"] == "held"
        with pytest.raises(RuntimeStoreError) as error:
            runtime.mutate_worker(**scope, sequence=worker.journal["next_sequence"], operation="compression.context",
                                  payload={"target": "foreign"})
        assert error.value.reason == "permission_denied"
    finally:
        worker.failure = None
        worker.journal["pending"] = []
        worker.close()
