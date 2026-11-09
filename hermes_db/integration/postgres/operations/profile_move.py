"""Current PG Profile copy/retirement with exact snapshot and recipient proofs."""

from copy import deepcopy
import hmac
import json
from pathlib import Path
import uuid

from sqlalchemy import select

from hermes_db.errors import StorageConfigurationError, RetryableStorageError
from hermes_db.integration.transfer.move_values import imported_key, prepared_key, recipient_snapshot_digest, snapshot_digest
from hermes_db.integration.postgres.operations import file_grants
from hermes_db.domains.sessions.postgres.operations import retirement, retirement_guards as guards, sessions as lifecycle
from hermes_db.domains.sessions.postgres.queries import messages as transcript, prompts, sessions
from hermes_db.domains.runtime.postgres.queries import runtime
from hermes_db.integration.postgres.queries import profile_move as repo
from hermes_db.scope import DatabaseScope
from hermes_db.tables.conversations import messages, session_model_usage, sessions as table
from hermes_db.core.values import decode_text, encode_text, model_config
from hermes_db.domains.runtime.values import RuntimeStoreError


def _meta(conn, scope, key):
    value = runtime.meta(conn, scope, key)
    return json.loads(value) if value is not None else None


def _put(conn, scope, key, value):
    runtime.set_meta(conn, scope, key, json.dumps(value, ensure_ascii=True))


def prepare(conn, scope, sid, binding):
    guards.lock_targets(conn, scope, [sid])
    if sessions.raw_session(conn, scope, sid) is None:
        return None
    members = repo.require_unledgered(conn, scope, sid)
    guards.require_unleased(conn, scope, members)
    payload = repo.snapshot(conn, scope, sid)
    digest = snapshot_digest(payload)
    previous = _meta(conn, scope, prepared_key(sid))
    ticket = previous if previous and previous["digest"] == digest and previous["resource"] == binding else {
        "digest": digest, "token": uuid.uuid4().hex, "resource": binding, "home": str(scope.profile_home), "targets": {}}
    _put(conn, scope, prepared_key(sid), ticket)
    payload["_pg_move"] = {"version": 1, "digest": digest, "token": ticket["token"], "resource": binding,
        "source_store_id": scope.require_store_id(), "source_home": str(scope.profile_home)}
    return payload


def validate(payload, scope, binding):
    proof = payload.get("_pg_move") if isinstance(payload, dict) else None
    if not isinstance(proof, dict) or proof.get("version") != 1:
        raise StorageConfigurationError("Profile moves accept current PostgreSQL exports only")
    if proof["resource"] != binding or proof["source_store_id"] == scope.require_store_id():
        raise StorageConfigurationError("PostgreSQL moves require distinct store_ids in the same shared schema")
    if not hmac.compare_digest(proof["digest"], snapshot_digest(payload)):
        raise RuntimeStoreError("move_snapshot_invalid")
    return proof


def _present(conn, scope, source, sid, digest, count):
    receipt = _meta(conn, scope, imported_key(source.store_id, sid))
    if not receipt or receipt["digest"] != digest:
        return False
    local = repo.snapshot(conn, scope, sid)
    return (local is not None and len(local["messages"]) >= count
        and receipt.get("recipient_digest") == recipient_snapshot_digest(local, count))


def _source_scope(conn, proof, sid):
    source = DatabaseScope(Path(proof["source_home"]), proof["source_store_id"])
    ticket = _meta(conn, source, prepared_key(sid))
    if not ticket or not hmac.compare_digest(ticket["token"], proof["token"]) or ticket["digest"] != proof["digest"]:
        raise RuntimeStoreError("move_snapshot_stale")
    return DatabaseScope(Path(ticket["home"]), source.store_id), ticket


def import_snapshot(conn, scope, payload, profile_name, binding):
    proof = validate(payload, scope, binding)
    sid = payload["session"]["id"]
    source, _ = _source_scope(conn, proof, sid)
    file_grants.lock_scopes(conn, [source, scope], receivers=[source])
    source, ticket = _source_scope(conn, proof, sid)
    if _present(conn, scope, source, sid, proof["digest"], len(payload["messages"])):
        _confirm(conn, source, scope, sid, ticket)
        return "present"
    if sessions.raw_session(conn, scope, sid) is not None:
        raise RuntimeStoreError("session_exists")
    current = repo.snapshot(conn, source, sid)
    if current is None or snapshot_digest(current) != proof["digest"]:
        raise RuntimeStoreError("move_snapshot_stale")
    members = repo.require_unledgered(conn, source, sid)
    guards.require_unleased(conn, source, members)
    _copy(conn, scope, payload, profile_name)
    file_grants.transfer(conn, source, scope, payload)
    recipient = recipient_snapshot_digest(repo.snapshot(conn, scope, sid), len(payload["messages"]))
    _put(conn, scope, imported_key(source.store_id, sid), {"digest": proof["digest"], "source_store_id": source.store_id,
        "recipient_digest": recipient})
    _confirm(conn, source, scope, sid, ticket)
    return "imported"


def _confirm(conn, source, target, sid, ticket):
    ticket = deepcopy(ticket)
    ticket["targets"][target.require_store_id()] = str(target.profile_home)
    _put(conn, source, prepared_key(sid), ticket)


def _copy(conn, scope, payload, profile_name):
    raw, sid = deepcopy(payload["session"]), payload["session"]["id"]
    parent = raw.get("parent_session_id")
    if parent and sessions.raw_session(conn, scope, parent) is None:
        parent = None
    lifecycle.create_on_connection(conn, scope, sid, raw["source"], own_profile=profile_name, parent_session_id=parent,
        model_config=model_config(raw["model_config"]), system_prompt=decode_text(payload["system_prompt"]))
    created = sessions.raw_session(conn, scope, sid)
    prompt = created["system_prompt_hash"]
    pin = prompts.store_prompt(conn, scope, decode_text(payload["tool_pin"]))
    raw.update(parent_session_id=parent, lineage_root_id=created["lineage_root_id"], profile_name=profile_name,
        system_prompt_hash=prompt, tool_names=pin)
    raw.update(_title(conn, scope, sid, raw["title"]))
    sessions.update_session(conn, scope, sid, {key: value for key, value in raw.items() if key != "id"})
    copied, slots = [], []
    for message in payload["messages"]:
        values = {key: value for key, value in message.items() if key != "id"}
        values["session_id"] = sid
        row_id = transcript.insert_row(conn, scope, values)
        copied.append(row_id)
        slots.append(message["display_order"] if message["display_order"] is not None else message["id"])
    slot_map = dict(zip(sorted(set(slots)), sorted(copied)))
    for row_id, slot in zip(copied, slots):
        conn.execute(messages.update().where(transcript.where(scope, [sid]), messages.c.id == row_id).values(display_order=slot_map[slot]))
    for usage in payload["usage"]:
        conn.execute(session_model_usage.insert().values(store_id=scope.require_store_id(), **usage))


def _title(conn, scope, sid, raw):
    title = decode_text(raw)
    if title is None:
        return {"title": None, "title_search": None}
    candidate, ordinal = title, 0
    while conn.scalar(select(table.c.id).where(table.c.store_id == scope.require_store_id(), table.c.id != sid,
        table.c.title == encode_text(candidate))) is not None:
        ordinal += 1
        suffix = f" ({sid[-12:]}{':' + str(ordinal) if ordinal > 1 else ''})"
        candidate = title[:100 - len(suffix)] + suffix
    return {"title": encode_text(candidate), "title_search": candidate.replace("\x00", "")}


def retire_source(conn, scope, sid):
    from hermes_db.integration.session_composition import SessionMedia
    if sessions.raw_session(conn, scope, sid) is None:
        return False
    ticket = _meta(conn, scope, prepared_key(sid))
    if ticket is None or not ticket["targets"]:
        raise RuntimeStoreError("move_not_confirmed")
    targets = [DatabaseScope(Path(home), store_id) for store_id, home in ticket["targets"].items()]
    planned = file_grants.lock_scopes(conn, [scope, *targets])
    ticket = _meta(conn, scope, prepared_key(sid))
    if set(ticket["targets"]) - set(planned):
        raise RetryableStorageError("Move recipient scopes changed; inspect the receipt before retrying")
    members = repo.require_unledgered(conn, scope, sid)
    guards.lock_targets(conn, scope, members)
    guards.require_unleased(conn, scope, members)
    snapshot = repo.snapshot(conn, scope, sid)
    if snapshot is None or snapshot_digest(snapshot) != ticket["digest"]:
        raise RuntimeStoreError("move_snapshot_changed")
    if not any(_present(conn, target, scope, sid, ticket["digest"], len(snapshot["messages"])) for target in targets):
        raise RuntimeStoreError("move_not_confirmed")
    retirement.retire_sessions(conn, scope, [sid], media_references=SessionMedia().admission_references)
    retirement.delete_rows(conn, scope, [sid])
    return True
