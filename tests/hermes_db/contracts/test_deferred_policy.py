"""Deferred picks retain exact receipts and latest-slot compare-and-swap semantics."""

import json
from types import SimpleNamespace


def test_deferred_pick_replay_never_overwrites_a_newer_pick_and_cas_is_exact(store, runtime):
    from gateway.session_contract import SessionRef
    from gateway.session_deferred_pick import _compare_pick, defer_pick
    from hermes_db.domains.runtime.receipts import DEFERRED_PICK_PREFIX
    store.create_session("s", "cli")
    epoch = runtime.begin_epoch(instance_id="owner")
    owner, actor = SimpleNamespace(db=store, epoch=epoch), SimpleNamespace(subject="human")
    ref = SessionRef("profile", "s")
    params = dict(request_id="first", operation="reasoning", payload={"effort": "low"}, expected_revision=0, expected_generation=0)
    first = defer_pick(owner, actor, ref, params)
    assert first["status"] == "deferred" and first["effort"] == "low"
    key = DEFERRED_PICK_PREFIX + "s"
    old = store.get_meta(key)
    defer_pick(owner, actor, ref, {**params, "request_id": "second", "payload": {"effort": "high"}})
    newer = store.get_meta(key)
    assert defer_pick(owner, actor, ref, params) == first
    assert store.get_meta(key) == newer
    assert not _compare_pick(owner, key, old, None)
    assert json.loads(store.get_meta(key))["reasoning"]["payload"]["effort"] == "high"
    assert _compare_pick(owner, key, newer, None)
    assert store.get_meta(key) is None
