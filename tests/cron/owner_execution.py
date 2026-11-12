"""Real cron owner execution seam used by scheduler behavior tests."""

import asyncio
import json
from types import SimpleNamespace


def run_owned_job(job, tmp_path, db=None):
    """Run the production owner bridge, preserving each test's agent/DB probes."""
    from gateway.session_contract import SessionRef
    from gateway.session_cron import current_execution, execute
    from hermes_state_registry import acquire, release

    ref = SessionRef("test-profile", "canonical-cron-session")
    admission_id = "cron-owner-admission"
    request_id = "cron-owner-request"
    owns_db = db is None
    if owns_db:
        from hermes_state import SessionDB

        SessionDB(tmp_path / "state.db").close()
        db = acquire(tmp_path / "state.db")
        db.create_session(ref.session_id, source="cron")
    else:
        db.db_path = str(tmp_path / "state.db")
    authority = SimpleNamespace(
        db=db,
        sessions={ref.session_id: SimpleNamespace(source=SimpleNamespace(user_id="cron-owner"))},
        pending_results={},
    )
    row = {
        "admission_id": admission_id, "request_id": request_id,
        "principal_id": "cron-owner", "owner_epoch": 1, "generation": 1, "payload": {"text": ""},
    }
    policy = SimpleNamespace(request_json=json.dumps({
        "cron_job": job, "extra_prompt": None, "request_id": request_id,
    }))

    async def run():
        previous = current_execution()
        try:
            await execute(authority, ref, row, policy)
        except RuntimeError as exc:
            saved = authority.pending_results.get(admission_id)
            if saved is None:
                raise
            assert str(exc) == saved["result"]["cron_result"][3]
        assert current_execution() is previous
        assert authority._cron_cancellations == {}
        return tuple(authority.pending_results[admission_id]["result"]["cron_result"])

    try:
        return asyncio.run(run())
    finally:
        if owns_db:
            release(db)
