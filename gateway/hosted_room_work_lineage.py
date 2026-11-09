"""Validate passive evidence against committed authority spans, never elect an owner."""
from hermes_db.domains.rooms.work_rules import validate_provenance
from gateway.hosted_room_authority_history import TRANSFER_KINDS, at_sequence, read_history_locked, validate_history


def source_prefix_locked(conn, room_id, authority, seq):
    from gateway.hosted_room_work_records import WorkRecordPrefixError, digest
    history = read_history_locked(conn, room_id, gateway_id=authority["gateway_id"], epoch=authority["epoch"])
    if history is None:
        raise WorkRecordPrefixError("successor work evidence has no verified lineage")
    spans = validate_history(history, gateway_id=authority["gateway_id"], epoch=authority["epoch"])
    count = 0
    import json
    for event in conn.execute("SELECT seq,authority_epoch,actor_json,kind FROM hosted_room_events WHERE room_id=? AND seq<=? ORDER BY seq", (room_id, seq)):
        count += 1
        span = at_sequence(spans, count)
        actor = json.loads(event["actor_json"])
        boundary = span.epoch > 1 and count == span.from_seq
        if (event["seq"] != count or event["authority_epoch"] != span.epoch
                or (actor.get("kind") == "gateway" and actor.get("id") != span.gateway_id)
                or (event["kind"] in TRANSFER_KINDS) != boundary):
            raise WorkRecordPrefixError("work record history prefix is not verified")
    if count != seq:
        raise WorkRecordPrefixError("work record history prefix is unavailable")
    return spans, digest(history)




def task_origins(record, spans):
    return {task["task_id"]: {"gateway_id": origin.gateway_id, "epoch": origin.epoch}
            for task in record["tasks"] for origin in [at_sequence(spans, task["source_event_seq"])]}
