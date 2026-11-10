"""Managed recall uses its authenticated owner; ordinary handles stay scoped as given."""
import json

import pytest

from agent.runtime_session_store import RuntimeSessionStore
from hermes_state import SessionDB
from tools.session_search_tool import session_search


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The worker's profile home: ``get_hermes_home()`` resolves to it, so its state.db is the DB."""
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    return tmp_path


def _seed(path, session_id, content):
    db = SessionDB(path / "state.db")
    db.create_session(session_id, source="cli")
    db.append_message(session_id, role="user", content=content)
    db.append_message(session_id, role="assistant", content="noted")
    return db


def test_worker_recall_uses_owner_rpc_without_opening_a_local_store(home, monkeypatch):
    db = _seed(home, "worker-s", "the zanzibar rollout is blocked on the store")
    calls = []

    def owner(method, **params):
        calls.append((method, params))
        return session_search(db=db, **params['options'])

    store = RuntimeSessionStore(owner, {"session_id": "worker-s", "epoch": 1}, home / "outbox")
    monkeypatch.setattr('hermes_cli.db_sessions.open_session_store', lambda *args, **kwargs: pytest.fail('worker opened a database'))
    try:
        payload = json.loads(session_search(query="zanzibar", db=store))
        assert calls[0][0] == 'worker.recall'
        assert calls[0][1]['epoch'] == 1
        assert store.journal['next_sequence'] == 1 and not store.journal['pending']
    finally:
        store.close()
        db.close()
    assert payload["success"] is True, payload
    assert [r["session_id"] for r in payload["results"]] == ["worker-s"]


def test_a_readable_handle_is_still_used_as_given(home, tmp_path):
    """A real SessionDB passed by a caller is not swapped for the home DB."""
    home_db = _seed(home, "home-session", "zanzibar appears only in the home transcript")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    passed = _seed(elsewhere, "passed-in", "zanzibar from the caller's handle")
    try:
        payload = json.loads(session_search(query="zanzibar", db=passed))
    finally:
        passed.close()
        home_db.close()
    assert [r["session_id"] for r in payload["results"]] == ["passed-in"]
