"""Current PG move fingerprints and opaque resource binding, never connection secrets."""

import hashlib
import json

PREPARED = "hermes:profile-move:prepared:"
IMPORTED = "hermes:profile-move:imported:"


def _bytes(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": bytes(value).hex()}
    raise TypeError(f"Unsupported move snapshot value: {type(value).__name__}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=_bytes).encode()).hexdigest()


def snapshot_digest(snapshot):
    # Parent-first source retirement detaches remaining children. Those map
    # changes must not masquerade as newly generated content in the next move.
    ignored = {"store_id", "parent_session_id", "lineage_root_id", "runtime_revision", "runtime_generation"}
    data = {name: snapshot[name] for name in ("session", "system_prompt", "tool_pin", "messages", "usage")}
    return digest({**data, "session": {name: value for name, value in snapshot["session"].items() if name not in ignored}})


def prepared_key(sid):
    return PREPARED + digest(sid)


def imported_key(source_store, sid):
    return IMPORTED + digest([source_store, sid])


def resource_key(transactions):
    url = transactions.engine.url
    endpoints = {name: value for name, value in url.query.items() if name in ("host", "hostaddr", "port", "dbname", "database", "service")}
    return digest([url.drivername, url.host, url.port, url.database, endpoints, transactions.schema])
