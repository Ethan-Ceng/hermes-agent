"""Collect real driver facts against one canonical history snapshot."""

import json

from sqlalchemy import or_, select
from gateway import hosted_room_driver as driver, hosted_room_work_records as native
from gateway import hosted_room_authority_history as history
from hermes_db.domains.rooms.postgres.queries import rooms as room_repo, work as repo
from hermes_db.tables.rooms import events, remote_runs
from hermes_db.tables.room_runs import tasks
from hermes_db.core.values import encode_text


def history_anchor(conn, store, room_id, seq):
    if seq == 0:
        return native.digest([])
    row = conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq == seq)).mappings().one_or_none()
    if row is None:
        raise native.WorkRecordPrefixError("work record history prefix is unavailable")
    row = room_repo.decode(row)
    return native.digest([row["seq"], row["event_id"], row["kind"], json.loads(row["actor_json"]),
        row["authority_epoch"], json.loads(row["payload_json"]), float(row["created_at"])])


def source_prefix(conn, store, room_id, authority, seq):
    transfers = [room_repo.decode(row) for row in conn.execute(select(events).where(room_repo.scope(events, store, room_id),
        events.c.kind.in_([encode_text(kind) for kind in history.TRANSFER_KINDS])).order_by(events.c.seq).limit(
            history.MAX_AUTHORITY_SPANS)).mappings()]
    lineage = history.history_from_rows(transfers, gateway_id=authority["gateway_id"], epoch=authority["epoch"])
    if lineage is None:
        raise native.WorkRecordPrefixError("successor work evidence has no verified lineage")
    spans = history.validate_history(lineage, gateway_id=authority["gateway_id"], epoch=authority["epoch"])
    count = 0
    for row in conn.execute(select(events).where(room_repo.scope(events, store, room_id), events.c.seq <= seq).order_by(events.c.seq)).mappings():
        count += 1
        event = room_repo.decode(row)
        span, actor = history.at_sequence(spans, count), json.loads(event["actor_json"])
        boundary = span.epoch > 1 and count == span.from_seq
        if (event["seq"] != count or event["authority_epoch"] != span.epoch
                or (actor.get("kind") == "gateway" and actor.get("id") != span.gateway_id)
                or (event["kind"] in history.TRANSFER_KINDS) != boundary):
            raise native.WorkRecordPrefixError("work record history prefix is not verified")
    if count != seq:
        raise native.WorkRecordPrefixError("work record history prefix is unavailable")
    return spans, native.digest(lineage)


def _task_values(rows):
    result = []
    for row in rows:
        row = room_repo.decode(row)
        try:
            payload, encoded, digest = driver._task_payload(json.loads(row["payload_json"]))
        except (ValueError, driver.DriverStateError):
            return [], "unsupported_task"
        if digest != row["payload_digest"] or encoded != row["payload_json"] or payload["source_event_seq"] != row["source_event_seq"]:
            return [], "unsupported_task"
        result.append({**{key: row[key] for key in native._TASK_FIELDS - {"payload_sha256", "phase", "member_id", "profile"}},
            "payload_sha256": digest, "phase": row["status"], "profile": payload["target_profile"],
            "member_id": payload.get("target_member_id", payload["target_profile"])})
    return result, None


def capture_tasks(conn, store, room_id):
    rows = conn.execute(select(tasks).where(room_repo.scope(tasks, store, room_id),
        or_(tasks.c.status.not_in(driver.TERMINAL_STATUSES), repo.unpublished(tasks, store))).order_by(
            tasks.c.task_id).limit(native.MAX_TASKS + 1)).mappings().all()
    receipts = [room_repo.record(row) for row in conn.execute(select(*[remote_runs.c[key] for key in sorted(native._RECEIPT_FIELDS)]).where(
        room_repo.scope(remote_runs, store, room_id), repo.unpublished(remote_runs, store)).order_by(
            remote_runs.c.task_id, remote_runs.c.execution_generation, remote_runs.c.member_id).limit(native.MAX_RECEIPTS + 1)).mappings()]
    if len(rows) > native.MAX_TASKS or len(receipts) > native.MAX_RECEIPTS:
        return [], [], "bounds_exceeded"
    values, reason = _task_values(rows)
    return ([], [], reason) if reason else (values, receipts, None)


def content(conn, store, room):
    room_id, seq = room["room_id"], room["next_seq"] - 1
    values, receipts, reason = capture_tasks(conn, store, room_id)
    stop = conn.execute(select(events).where(room_repo.scope(events, store, room_id),
        events.c.kind == encode_text("room.stop_requested")).order_by(events.c.seq.desc()).limit(1)).mappings().one_or_none()
    stop = room_repo.decode(stop) if stop is not None else None
    result = dict(version=1 if room["authority_epoch"] == 1 else 2, room_id=room_id,
        home_install_id=room["authority_gateway_id"], authority=dict(gateway_id=room["authority_gateway_id"], epoch=room["authority_epoch"]),
        roster_sha256=native.roster_digest(json.loads(room["members_json"])),
        history=dict(seq=seq, event_sha256=history_anchor(conn, store, room_id, seq)),
        availability="unavailable" if reason else "available", reason=reason,
        tasks=values, receipts=receipts, limitations=native.LIMITATIONS,
        stop=dict(closing=False, revocation_complete=False, seq=stop["seq"] if stop else 0,
                  cancel_id=json.loads(stop["payload_json"]).get("cancel_id") if stop else None))
    spans = None
    if result["version"] == 2:
        spans, result["lineage_sha256"] = source_prefix(conn, store, room_id, result["authority"], seq)
        result["incompleteness"] = ["prior_authority_work_unknown"]
    return result, spans
