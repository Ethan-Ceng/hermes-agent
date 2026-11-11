"""RetainDB exact request identity, destination fencing and durable token CAS."""

from dataclasses import replace
import pytest
from sqlalchemy import update
from plugins.plugin_storage import capture_queue, open_queue
from hermes_db.errors import StorageConflictError
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
import plugins.plugin_storage as _plugin_storage_application
from hermes_db.tables.retain_queue import pending

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_request_identity_acknowledged_receipt_and_destination_scope(pg_profiles):
    with pg_profiles("one") as home:
        reference = capture_queue(home, "destination-a")
        record = operations.prepare(reference, "request", "user\x00🙂", "session\x00🙂", [{"zero": 0, "false": False, "none": None, "text": "值\x00🙂"}])
        first = _plugin_storage_application.retain_enqueue(reference, record)
        assert _plugin_storage_application.retain_enqueue(reference, record)["sequence"] == first["sequence"]
        with pytest.raises(StorageConflictError):
            _plugin_storage_application.retain_enqueue(reference, operations.prepare(reference, "request", "user\x00🙂", "session\x00🙂", ["different"]))
        other = replace(reference, destination_id="destination-b")
        assert _plugin_storage_application.retain_claim(other) is None
        assert _plugin_storage_application.retain_inspect(other, "request") is None
        assert _plugin_storage_application.retain_counts(other)["other_destination"] == 1
        claimed = _plugin_storage_application.retain_claim(reference)
        assert claimed["request_id"] == "request" and claimed["attempts"] == 1
        assert not _plugin_storage_application.retain_renew(other, "request", claimed["claim_token"])
        assert not _plugin_storage_application.retain_acknowledge(other, "request", claimed["claim_token"])
        assert _plugin_storage_application.retain_acknowledge(reference, "request", claimed["claim_token"])
        replayed = _plugin_storage_application.retain_enqueue(reference, record)
        assert replayed["status"] == "acknowledged" and replayed["messages_json"] is None
        assert _plugin_storage_application.retain_claim(reference) is None
    with pg_profiles("two") as home:
        peer = capture_queue(home, "destination-a")
        assert _plugin_storage_application.retain_inspect(peer, "request") is None
        assert _plugin_storage_application.retain_counts(peer) == dict(pending=0, other_destination=0, acknowledged=0)


def test_expired_claim_retake_fences_old_sender_renewal_ack_and_failure(pg_profiles):
    with pg_profiles("one") as home:
        reference = capture_queue(home, "destination")
        _plugin_storage_application.retain_enqueue(reference, operations.prepare(reference, "request", "user", "session", ["frozen"] ))
        first = _plugin_storage_application.retain_claim(reference)
        assert _plugin_storage_application.retain_renew(reference, "request", first["claim_token"])
        with open_queue(reference, write=True) as conn:
            conn.execute(update(pending).where(operations.key(reference, "request")).values(lease_until=0))
        assert not _plugin_storage_application.retain_renew(reference, "request", first["claim_token"])
        second = _plugin_storage_application.retain_claim(reference)
        assert second["claim_token"] != first["claim_token"] and second["attempts"] == 2
        assert not _plugin_storage_application.retain_acknowledge(reference, "request", first["claim_token"])
        assert not _plugin_storage_application.retain_fail(reference, "request", first["claim_token"], "stale")
        assert _plugin_storage_application.retain_inspect(reference, "request")["claim_token"] == second["claim_token"]
        assert _plugin_storage_application.retain_acknowledge(reference, "request", second["claim_token"])
