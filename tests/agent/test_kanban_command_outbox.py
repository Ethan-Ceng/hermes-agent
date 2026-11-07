"""A domain command waits for its own receipt without consuming session persist sequence."""

import json

import pytest

from agent.runtime_session_store import RuntimeSessionStore, WorkerPersistenceError


def test_command_ack_loss_freezes_payload_blocks_followups_and_reopens_same_id(tmp_path):
    calls = []
    payload = {"task_id": "one", "body": "frozen"}

    def offline(method, **params):
        calls.append((method, params))
        payload["body"] = "caller changed"
        raise TimeoutError("lost command ACK")

    scope = {"session_id": "session", "execution_id": "worker", "epoch": 1}
    store = RuntimeSessionStore(offline, scope, tmp_path / "outbox")
    try:
        with pytest.raises(TimeoutError, match="lost command ACK"):
            store.kanban_command("add_comment", payload)
        disk = json.loads(store.path.read_text())
        pending = disk["kanban_pending"]
        assert pending["payload"]["body"] == "frozen" and len(pending["command_id"]) == 32
        assert disk["next_sequence"] == 1 and disk["pending"] == []
        assert calls[0][0] == "worker.kanban.command"
        with pytest.raises(WorkerPersistenceError):
            store.queue_token_counts("session", input_tokens=1)
        with pytest.raises(WorkerPersistenceError):
            store.kanban_read("get_task", {"task_id": "one"})
    finally:
        store._outbox_owner.close()

    def committed(method, **params):
        calls.append((method, params))
        return {"value": 42}

    restored = RuntimeSessionStore(committed, scope, tmp_path / "outbox")
    try:
        assert calls[-1][0] == "worker.kanban.command"
        assert calls[-1][1]["command_id"] == pending["command_id"]
        assert calls[-1][1]["payload"] == pending["payload"]
        assert restored.journal["kanban_pending"] is None
        assert restored.journal["next_sequence"] == 1
        restored.queue_token_counts("session", input_tokens=1)
        assert calls[-1][0] == "worker.persist" and calls[-1][1]["sequence"] == 1
    finally:
        restored.close()


def test_command_refuses_to_cross_pending_session_receipt(tmp_path):
    def offline(*args, **kwargs):
        raise TimeoutError("session receipt missing")

    store = RuntimeSessionStore(offline, {"session_id": "session"}, tmp_path / "outbox")
    try:
        with pytest.raises(TimeoutError):
            store.queue_token_counts("session", input_tokens=1)
        with pytest.raises(WorkerPersistenceError):
            store.kanban_command("add_comment", {"task_id": "one", "body": "later"})
        assert store.journal.get("kanban_pending") is None
    finally:
        store._outbox_owner.close()
