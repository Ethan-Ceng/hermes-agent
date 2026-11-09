"""Request identity recovers a lost commit confirmation without repeating effects."""

from contextlib import contextmanager

import pytest


def test_admission_lost_confirmation_can_be_queried_and_replayed_once(core_pair, monkeypatch):
    from hermes_db.errors import UnknownCommitError
    from hermes_db.domains.runtime.postgres.operations.effects import CoreEffect
    from hermes_db.domains.runtime.postgres.queries import runtime as repo
    from hermes_db.domains.runtime.postgres.store import PostgresRuntimeStore

    store = core_pair[0]
    runtime = PostgresRuntimeStore(store)
    store.create_session("s", "test")
    epoch = runtime.begin_epoch(instance_id="owner")
    write = store._transactions.write
    calls = []

    def effect(conn, scope):
        calls.append("authorized")
        repo.set_meta(conn, scope, "proof", "once")

    @contextmanager
    def lose_confirmation():
        with write() as conn:
            yield conn
        raise UnknownCommitError("Lost commit confirmation")

    args = dict(epoch=epoch, principal_id="human", session_id="s", request_id="r", payload={"text": "ask"},
                _authorize_write=CoreEffect(effect))
    with monkeypatch.context() as patch:
        patch.setattr(store._transactions, "write", lose_confirmation)
        with pytest.raises(UnknownCommitError):
            runtime.admit_input(**args)
    accepted = runtime.find_admission(principal_id="human", session_id="s", request_id="r")
    assert accepted is not None and accepted["status"] == "queued"
    assert runtime.admit_input(**args) == accepted
    assert len(runtime.list_admissions(session_id="s")) == 1 and calls == ["authorized"]
