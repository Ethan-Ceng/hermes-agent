"""Current API session binding and route ownership on one scoped Core connection."""

from datetime import datetime
import json

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.operations import sessions as lifecycle
from hermes_db.domains.runtime.postgres.operations.effects import invoke
from hermes_db.domains.sessions.postgres.queries import gateway, retirement_housekeeping, sessions
from hermes_db.domains.runtime.postgres.queries import runtime, terminal
from hermes_db.tables.conversations import sessions as table
from hermes_db.tables.gateway import gateway_routing
from hermes_db.tables.runtime import session_admissions
from hermes_db.core.values import encode_text
from hermes_db.domains.runtime.receipts import API_BINDING_PREFIX, API_DECLARED_PREFIX
from hermes_db.domains.runtime.values import RuntimeStoreError, _json


def bind(conn, scope, *, epoch, receipt, storage_source, title, own_profile, guard=None, walked_from=None):
    runtime.require_epoch(conn, scope, epoch)
    sessions.lock_store(conn, scope, exclusive=True)
    invoke(guard, conn, scope)
    sid, route = receipt["session_id"], receipt["route"]
    if sessions.retired_session(conn, scope, sid):
        raise RuntimeStoreError("not_found")
    if walked_from:
        from hermes_db.domains.runtime.values import api_generation_id
        if not retirement_housekeeping.keep_passed(conn, scope, lambda n: api_generation_id(walked_from, n), sid):
            raise RuntimeStoreError("chain_moved")
    declared = receipt.get("declared_key")
    saved = runtime.meta(conn, scope, API_BINDING_PREFIX + sid)
    if saved is not None:
        current = json.loads(saved)
        if current.get("storage_source", "api_server") != storage_source:
            raise RuntimeStoreError("permission_denied")
        if declared and current.get("declared_key") != declared:
            raise RuntimeStoreError("admission_conflict")
        return
    _declare(conn, scope, declared, sid)
    row = sessions.raw_session(conn, scope, sid)
    _check_row(conn, scope, row, sid, storage_source, title, route)
    held = conn.scalar(select(gateway_routing.c.entry_json).where(*gateway.where(scope, ""),
        gateway_routing.c.session_key == route))
    holder = json.loads(held)["session_id"] if held is not None else sid
    if holder != sid and runtime.meta(conn, scope, API_BINDING_PREFIX + holder) is not None:
        raise RuntimeStoreError("admission_conflict")
    entry, source = receipt["entry"], receipt["entry"]["origin"]
    if row is None:
        lifecycle.create_on_connection(conn, scope, sid, storage_source, own_profile=own_profile)
        sessions.update_session(conn, scope, sid, {"title": encode_text(title), "title_search": title,
            "hidden": int(storage_source == "bot_room"), "started_at": datetime.fromisoformat(entry["created_at"]).timestamp()})
    else:
        sessions.lock_session(conn, scope, sid)
    sessions.update_session(conn, scope, sid, {"session_key": route, "chat_id": sid, "user_id": source["user_id"],
        "chat_type": "dm", "origin_json": _json(source)})
    if not gateway.save_route(conn, scope, "", route, _json(entry), datetime.fromisoformat(entry["updated_at"]).timestamp()):
        raise RuntimeStoreError("not_found")
    runtime.set_meta(conn, scope, API_BINDING_PREFIX + sid, _json(receipt))


def _declare(conn, scope, key, sid):
    if not key:
        return
    old = runtime.meta(conn, scope, API_DECLARED_PREFIX + key)
    if old is not None and old != sid:
        raise RuntimeStoreError("admission_conflict")
    runtime.set_meta(conn, scope, API_DECLARED_PREFIX + key, sid)


def admit_target(conn, scope, *, session_id, request_id, settings_key, settings, client_key):
    conflict = conn.scalar(select(session_admissions.c.admission_id).where(
        session_admissions.c.store_id == scope.require_store_id(),
        session_admissions.c.principal_id == "api", session_admissions.c.request_id == request_id,
        session_admissions.c.target_session_id != session_id).limit(1))
    if conflict is not None or (client_key and any(row["target_session_id"] != session_id
            for row in terminal.api_admissions(conn, scope, request_id))):
        raise RuntimeStoreError("admission_conflict")
    runtime.set_meta(conn, scope, settings_key, _json(settings))


def _check_row(conn, scope, row, sid, source, title, route):
    if row is not None and row["source"] != source:
        raise RuntimeStoreError("permission_denied")
    if row is not None and row["session_key"] not in (None, "", route):
        raise RuntimeStoreError("admission_conflict")
    if source == "bot_room":
        if row is not None and row["title"] != encode_text(title):
            raise RuntimeStoreError("admission_conflict")
        if conn.scalar(select(table.c.id).where(table.c.store_id == scope.require_store_id(),
                table.c.title == encode_text(title), table.c.id != sid).limit(1)) is not None:
            raise RuntimeStoreError("admission_conflict")
