"""Owner/recipient reference grants use scoped keys and exact random credentials."""

import hmac
import json

from sqlalchemy import select

from hermes_db.errors import StorageError
from hermes_db.repositories import runtime
from hermes_db.tables.runtime import state_meta

OWNED = "hermes:files:owned-grant:"
RECEIVED = "hermes:files:received-grant:"


def rows(conn, scope, prefix):
    found = conn.execute(select(state_meta.c.key, state_meta.c.value).where(
        state_meta.c.store_id == scope.require_store_id(), state_meta.c.key.startswith(prefix, autoescape=True)).limit(20001)).all()
    if len(found) > 20000:
        raise StorageError("File reference set exceeds the bounded verification limit")
    return [(key, json.loads(raw)) for key, raw in found]


def put(conn, scope, key, value):
    runtime.set_meta(conn, scope, key, json.dumps(value, ensure_ascii=True))


def drop(conn, scope, key):
    conn.execute(state_meta.delete().where(state_meta.c.store_id == scope.require_store_id(), state_meta.c.key == key))


def owned(conn, scope, proof, recipient):
    raw = runtime.meta(conn, scope, OWNED + proof["grant_id"])
    value = json.loads(raw) if raw is not None else None
    if not value or value.get("recipient_store_id") != recipient.require_store_id():
        return None
    return value if hmac.compare_digest(value["token"], proof["token"]) else None


def pins(conn, scope):
    names, media = set(), {}
    for _, value in rows(conn, scope, OWNED):
        names.update(value["files"]["spillover"])
        media.update({reference["path"]: reference for reference in value["files"]["media"]})
    return names, list(media.values())
