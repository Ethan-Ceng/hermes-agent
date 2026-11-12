"""Upstream resumable delegation records follow the selected dataset without SQLite access."""
import time
from types import SimpleNamespace

import pytest


@pytest.mark.integration
def test_resumable_claim_is_atomic_and_scoped_to_the_selected_postgresql_store(pg_pair):
    from tools import delegate_tool_resumable as records
    parents = [SimpleNamespace(_session_db=store, session_id="owner") for store in pg_pair]
    locations = [records._db_path_for(parent) for parent in parents]
    for location, label in zip(locations, ("alpha", "beta")):
        records._write(location, lambda ledger: records._upsert(
            ledger, "child", {"session_id": "child-session", "owners": ["owner"], "label": label},
            state="resumable", pinned=False, expires_at=time.time() + 3600))
    first, error = records.claim(parents[0], "child")
    assert error is None and first["label"] == "alpha"
    repeated, error = records.claim(parents[0], "child")
    assert repeated is None and error
    second, error = records.claim(parents[1], "child")
    assert error is None and second["label"] == "beta"
    records.release(parents[0], "child", first)
    assert records.claim(parents[0], "child")[0]["label"] == "alpha"


@pytest.mark.integration
def test_postgresql_resumable_recovery_and_pins_use_the_captured_owner(pg_store, tmp_path):
    from tools import delegate_tool_resumable as records
    parent = SimpleNamespace(_session_db=pg_store, session_id="owner")
    location = records._db_path_for(parent)
    record = {"session_id": "child-session", "owners": ["owner"], "delegation_id": "unit",
              "owner_pid": 0, "owner_started_at": 0, "pin_paths": [str(tmp_path)]}
    records._write(location, lambda ledger: records._upsert(
        ledger, "dead-child", record, state="running", pinned=True, expires_at=time.time() + 3600))
    plan = records.plan_recovery(location, lambda pid, started: False)
    assert "dead-child" in plan
    recovered = records._write(location, lambda ledger: records.recover_abandoned(ledger, plan))
    assert recovered == {"unit": ["dead-child"]}
    saved = records._write(location, lambda ledger: records._row(ledger, "dead-child"))
    assert saved["state"] == "resumable" and saved["outcome"] == "unknown"
    assert dict(records._read_pins(location, time.time()))["dead-child"]["session_id"] == "child-session"
