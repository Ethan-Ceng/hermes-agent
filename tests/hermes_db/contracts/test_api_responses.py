"""Durable response bodies and compact request identities have different lifetimes."""

import pytest


@pytest.fixture
def response_factory(store):
    from hermes_state import SessionDB
    children = []

    def create(**options):
        if isinstance(store, SessionDB):
            from gateway.platforms.api_server_response_store import ResponseStore
            child = ResponseStore(db_path=str(store.db_path.parent / "response_store.db"), **options)
        else:
            from hermes_db.domains.runtime.postgres.response_store import PostgresResponseStore
            child = PostgresResponseStore(store, **options)
        children.append(child)
        return child

    yield create
    for child in children:
        child.close()


def test_response_identity_model_and_output_order_survive_body_eviction_and_reopen(response_factory):
    store = response_factory(max_size=2, max_identities=10)
    key = "idem:request"
    assert store.bind_request_key(key, "fingerprint", model="wire-label")
    assert not store.bind_request_key(key, "different", model="other")
    store.bind_request_admission(key, "admission")
    assert store.output_index(key, "tool") == 0 and store.output_index(key, "answer") == 1
    store.put(key, {"response": {"id": "response", "status": "completed"}})
    store.put("body", {"conversation_history": [{"role": "user", "content": "exact\x00"}]})
    store.set_conversation("named", "body")
    store.put("later", {"value": "later"})
    store.put("newest", {"value": "newest"})
    assert store.get("body") is None and store.get_conversation("named") is None
    store.close()
    reopened = response_factory(max_size=2, max_identities=10)
    assert reopened.request_key_matches(key, "fingerprint") and not reopened.request_key_matches(key, "different")
    assert reopened.request_model(key, "changed-default") == "wire-label"
    assert reopened.request_admission(key) == "admission"
    assert reopened.output_index(key, "tool") == 0 and reopened.output_index(key, "third") == 2


def test_response_retry_envelope_is_immutable_and_chained_body_remains_exact(response_factory):
    store = response_factory(max_size=10)
    key = "idem:request"
    store.bind_request_key(key, "fingerprint")
    initial = {"response": {"id": "r", "output": [{"id": "item", "text": "first\x00"}]}}
    store.put(key, initial)
    store.put(key, {"response": {"id": "changed"}})
    assert store.get(key) == initial
    data = {"conversation_history": [{"role": "user", "content": "prefix\x00"}], "instructions": "exact\n"}
    store.put("r", data)
    store.set_conversation("conversation", "r")
    assert store.get(store.get_conversation("conversation")) == data
    assert store.delete("r")
    assert store.request_admission(key) is None and store.get(key) is None
    assert not store.delete("r")


def test_only_settled_response_identities_join_retention_bound(response_factory):
    store = response_factory(max_size=10, max_identities=1)
    store.bind_request_key("idem:pending", "pending")
    store.bind_request_admission("idem:pending", "unsettled")
    store.bind_request_key("idem:old", "old")
    store.output_index("idem:old", "old-item")
    store.put("idem:old", {"response": {"id": "old", "status": "completed"}})
    store.bind_request_key("idem:new", "new")
    store.put("idem:new", {"response": {"id": "new", "status": "completed"}})
    assert store.request_created_at("idem:old") is None
    assert store.request_created_at("idem:pending") is not None
    assert store.request_admission("idem:pending") == "unsettled"
    store.forget_unadmitted_request("idem:pending")
    assert store.request_admission("idem:pending") == "unsettled"
    store.bind_request_key("idem:refused", "refused")
    store.forget_unadmitted_request("idem:refused")
    assert store.request_created_at("idem:refused") is None


def test_zero_body_capacity_still_settles_and_bounds_request_identity(response_factory):
    store = response_factory(max_size=0, max_identities=1)
    for label in ("old", "new"):
        key = "idem:" + label
        store.bind_request_key(key, label)
        store.put(key, {"response": {"id": label, "status": "completed"}})
    assert len(store) == 0
    assert store.request_created_at("idem:old") is None
    assert store.request_created_at("idem:new") is not None
