"""RetainDB exact request identity, destination fencing and durable token CAS."""

from dataclasses import replace
import pytest
from sqlalchemy import update
from hermes_db.domains.plugin_storage.retain.api import capture_queue, open_queue
from hermes_db.errors import StorageConflictError
from hermes_db.domains.plugin_storage.retain.postgres.operations import queue as operations
from hermes_db.tables.retain_queue import pending

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_request_identity_acknowledged_receipt_and_destination_scope(pg_profiles):
    with pg_profiles("one") as home:
        reference = capture_queue(home, "destination-a")
        record = operations.prepare(reference, "request", "user\x00🙂", "session\x00🙂", [{"zero": 0, "false": False, "none": None, "text": "值\x00🙂"}])
        first = operations.enqueue(reference, record)
        assert operations.enqueue(reference, record)["sequence"] == first["sequence"]
        with pytest.raises(StorageConflictError):
            operations.enqueue(reference, operations.prepare(reference, "request", "user\x00🙂", "session\x00🙂", ["different"]))
        other = replace(reference, destination_id="destination-b")
        assert operations.claim(other) is None
        assert operations.inspect(other, "request") is None
        assert operations.counts(other)["other_destination"] == 1
        claimed = operations.claim(reference)
        assert claimed["request_id"] == "request" and claimed["attempts"] == 1
        assert not operations.renew(other, "request", claimed["claim_token"])
        assert not operations.acknowledge(other, "request", claimed["claim_token"])
        assert operations.acknowledge(reference, "request", claimed["claim_token"])
        replayed = operations.enqueue(reference, record)
        assert replayed["status"] == "acknowledged" and replayed["messages_json"] is None
        assert operations.claim(reference) is None
    with pg_profiles("two") as home:
        peer = capture_queue(home, "destination-a")
        assert operations.inspect(peer, "request") is None
        assert operations.counts(peer) == dict(pending=0, other_destination=0, acknowledged=0)


def test_expired_claim_retake_fences_old_sender_renewal_ack_and_failure(pg_profiles):
    with pg_profiles("one") as home:
        reference = capture_queue(home, "destination")
        operations.enqueue(reference, operations.prepare(reference, "request", "user", "session", ["frozen"] ))
        first = operations.claim(reference)
        assert operations.renew(reference, "request", first["claim_token"])
        with open_queue(reference, write=True) as conn:
            conn.execute(update(pending).where(operations.key(reference, "request")).values(lease_until=0))
        assert not operations.renew(reference, "request", first["claim_token"])
        second = operations.claim(reference)
        assert second["claim_token"] != first["claim_token"] and second["attempts"] == 2
        assert not operations.acknowledge(reference, "request", first["claim_token"])
        assert not operations.fail(reference, "request", first["claim_token"], "stale")
        assert operations.inspect(reference, "request")["claim_token"] == second["claim_token"]
        assert operations.acknowledge(reference, "request", second["claim_token"])
