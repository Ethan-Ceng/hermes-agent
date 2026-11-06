"""Owner recall verifies the adopted execution before reading profile history."""

import json
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_worker_recall_reads_owner_backend_and_refuses_stale_or_forged_claim(store, runtime, monkeypatch):
    from gateway.session_worker_recall import worker_recall
    from hermes_db.health import profile_home_for_store
    from hermes_state_runtime import RuntimeStoreError
    store.create_session("working", "cli")
    store.create_session("prior", "cli")
    store.append_message("prior", "user", "prior conversation")
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.register_worker(epoch=epoch, execution_id="worker", session_id="working", generation=0,
        kind="compute", adoption_secret="verified-claim")
    runtime.adopt_worker(epoch=epoch, execution_id="worker", session_id="working", generation=0,
        adoption_secret="verified-claim")
    home = profile_home_for_store(store)
    authority = SimpleNamespace(db=store, epoch=epoch, profile_id=str(home))
    connection = SimpleNamespace(authority=authority, actor=SimpleNamespace(
        profile_id=str(home), capabilities=frozenset({"worker:adopt"})))
    monkeypatch.setattr("gateway.session_worker._claim", lambda *args: "verified-claim")
    params = dict(profile_id=str(home), session_id="working", execution_id="worker", generation=0,
        pid=123, birth=123.0, secret="client-proof", epoch=epoch, options={"session_id": "prior"})
    result = json.loads(await worker_recall(connection, None, params))
    assert result["success"] and result["messages"][0]["content"] == "prior conversation"
    from tui_gateway.contracts.registry import CANONICAL_METHODS
    CANONICAL_METHODS['worker.recall'].params.model_validate(params)
    with pytest.raises(ValueError):
        CANONICAL_METHODS['worker.recall'].params.model_validate(params | {'options': {'dsn': 'forbidden'}})
    from gateway.session_worker_reads import worker_read
    read = {key: value for key, value in params.items() if key != "options"}
    assert await worker_read(connection, None, read | {"operation": "session.persisted", "payload": {"session_id": "prior"}}) == "prior"
    assert await worker_read(connection, None, read | {"operation": "result.owns", "payload": {"owner": "prior", "parent": "prior"}})
    assert await worker_read(connection, None, read | {"operation": "cron.usage", "payload": {"job_id": "no-job", "execution_id": "no-run"}}) == {}
    with pytest.raises(RuntimeStoreError, match="invalid_params"):
        await worker_read(connection, None, read | {"operation": "sql", "payload": {}})
    monkeypatch.setattr("gateway.session_worker._claim", lambda *args: "forged-claim")
    with pytest.raises(RuntimeStoreError, match="permission_denied"):
        await worker_recall(connection, None, params)
    monkeypatch.setattr("gateway.session_worker._claim", lambda *args: "verified-claim")
    authority.epoch = runtime.begin_epoch(instance_id="replacement")
    with pytest.raises(RuntimeStoreError, match="stale_epoch|stale_generation"):
        await worker_recall(connection, None, params)
    with pytest.raises(RuntimeStoreError, match="stale_epoch|stale_generation"):
        await worker_read(connection, None, read | {"operation": "session.persisted", "payload": {"session_id": "prior"}})
