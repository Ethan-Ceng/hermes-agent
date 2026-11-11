"""Business delivery contract shared with real PG, without SQL-specific assertions."""


def exercise_delivery_contract(queue):
    payload = {"id": "job", "types": [False, 0, "0", None, {}], "text": "中文\x00🙂"}
    queue.enqueue("exec", payload, "content\x00🙂", for_failure=True)
    assert queue.get_status("exec")["status"] == "pending"
    sent = []
    assert queue.drain(lambda job, content, failure: sent.append((job, content, failure))) == 1
    assert sent == [(payload, "content\x00🙂", True)]
    assert queue.get_status("exec")["status"] == "delivered"
    assert queue.enqueue("exec", {"id": "replayed"}, "replayed")["status"] == "delivered"
    assert queue.drain(lambda *args: sent.append(args)) == 0
    assert len(sent) == 1
    queue.enqueue("waiting", {"id": "other"}, "queued")
    assert queue.enqueue_and_wait("waiting", {"id": "other"}, "queued", timeout=0) is None
    assert queue.get_status("waiting")["status"] == "pending"


def test_sqlite_delivery_contract(tmp_path, monkeypatch):
    from cron import delivery_queue as queue
    monkeypatch.setattr(queue, "DELIVERY_DB", tmp_path / "deliveries.db")
    monkeypatch.setattr(queue, "MAX_TERMINAL_DELIVERIES", 0)
    queue.initialize()
    exercise_delivery_contract(queue)
