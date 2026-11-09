"""Viewer CAS records and live-list metadata share the selected owner store."""

from types import SimpleNamespace
import json


def test_viewer_close_compare_delete_and_live_facts_are_backend_scoped(store, runtime):
    from gateway.session_live_listing import _store_facts
    from gateway.session_viewer_close import CLOSE_PREFIX, _busy, _idle_s, _persist_close, forget_persisted_close
    from hermes_db.domains.runtime.receipts import POLICY_PREFIX
    store.create_session("s", "cli")
    store.create_session("target", "cli")
    store.set_session_title("s", "会话")
    store.end_session("target", "closed")
    epoch = runtime.begin_epoch(instance_id="owner")
    owner = SimpleNamespace(db=store, epoch=epoch)
    _persist_close(owner, "s", "old-record")
    _persist_close(owner, "s", "new-record")
    assert not forget_persisted_close(owner, "s", "old-record")
    assert store.get_meta(CLOSE_PREFIX + "s") == "new-record"
    assert forget_persisted_close(owner, "s", "new-record")
    assert store.get_meta(CLOSE_PREFIX + "s") is None
    assert not _busy(owner, "s", "s")
    row = runtime.admit_input(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={"text": "queued"})
    assert _busy(owner, "s", "s")
    assert _idle_s(owner, "s") >= 0
    store.set_meta(POLICY_PREFIX + "s", json.dumps({"entry": {"session_id": "target"},
        "policy": {"skills_prompt": "before\x00after"}}))
    facts, pending = _store_facts(store, ["s", "absent"])
    assert list(facts) == ["s"] and facts["s"]["title"] == "会话"
    assert facts["s"]["target_ended_at"] == store.get_session("target")["ended_at"]
    assert pending["s"][0]["admission_id"] == row["admission_id"] and pending["s"][0]["status"] == "queued"
    _persist_close(owner, "s", "kept")
    runtime.begin_epoch(instance_id="replacement")
    assert not forget_persisted_close(owner, "s", "kept")
    assert store.get_meta(CLOSE_PREFIX + "s") == "kept"
