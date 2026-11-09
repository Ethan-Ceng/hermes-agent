"""Ordinary API media stays held through settlement and releases after deletion."""

import base64
from pathlib import Path
from types import SimpleNamespace



PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="


def test_native_api_recovery_and_terminal_media_keep_history_until_delete(api_owner, monkeypatch):
    from gateway.session_api_turn import admit_api_turn, recover_authority_api_turns
    from gateway.session_ingress_media import collect_unheld_api_images, release_admission_media
    from hermes_db.integration.runtime_access import runtime_for_store
    owner, db, other = api_owner
    adapter = SimpleNamespace(gateway_runner=owner.runner, _ensure_session_db=lambda: db, _model_routes={})
    owner.runner._adapter_for_source = lambda source: adapter
    args = dict(session_id="image-holder", request_id="image-request", conversation_history=[{"role": "user", "content": "old"}],
        user_message=[{"type": "image_url", "image_url": {"url": "data:image/png;base64," + PNG}}])
    row = admit_api_turn(adapter, **args)[2]
    path = Path(row["payload"]["api_turn_v1"]["media"][0]["path"])
    assert path.read_bytes() == base64.b64decode(PNG)
    scheduled = []
    monkeypatch.setattr(owner, "_schedule", scheduled.append)
    recover_authority_api_turns(adapter, owner)
    assert [ref.session_id for ref in scheduled] == ["image-holder"]
    runtime = runtime_for_store(db)
    assert runtime_for_store(other).queued_api_sessions() == []
    claimed = runtime.claim_input(epoch=owner.epoch, session_id="image-holder")
    runtime.settle_input(epoch=owner.epoch, admission_id=row["admission_id"], generation=claimed["generation"], outcome="completed")
    assert release_admission_media(db, row["admission_id"]) == 0
    compacted = runtime.get_admission(admission_id=row["admission_id"])
    assert compacted["payload"]["api_turn_v1"]["history"] is None
    assert "data:image" not in compacted["payload"]["text"][0]["image_url"]["url"]
    assert admit_api_turn(adapter, **args)[2]["admission_id"] == row["admission_id"]
    assert collect_unheld_api_images(db) == 0 and path.exists()
    assert db.delete_session("image-holder")
    collect_unheld_api_images(db)
    assert not path.exists()
