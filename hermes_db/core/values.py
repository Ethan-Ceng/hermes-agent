"""Driver-free business value encoding. Never normalize stored prompt bytes."""

import json


def encode_text(value):
    return None if value is None else value.encode("utf-8")


def decode_text(value):
    return None if value is None else bytes(value).decode("utf-8")


def model_config(raw):
    if isinstance(raw, str):
        raw = json.loads(raw) if raw else None
    return dict(raw) if isinstance(raw, dict) else {}


def encode_config(config):
    return json.dumps(config) if config else None


def model_markers(raw):
    config = model_config(raw)
    origin = config.get('_delegate_from')
    return {'delegate_origin': encode_text(origin) if isinstance(origin, str) else None,
        'has_delegate_marker': int(origin is not None),
        'has_branch_marker': int(config.get('_branched_from') is not None)}


def explicit_fork(row, parent_id=None):
    parent_id = parent_id or row.get("parent_session_id")
    config = model_config(row.get("model_config"))
    return bool(parent_id) and (row.get("source") == "tool" or any(
        config.get(marker) == parent_id for marker in ("_branched_from", "_reset_from", "_delegate_from")))


def preferred_children(rows):
    roots = {row["id"]: row["lineage_root_id"] for row in rows}
    chosen = {}
    for row in rows:
        parent = row["parent_session_id"]
        if parent not in roots or roots[parent] != row["lineage_root_id"]:
            continue
        key = (2 if row["end_reason"] == "compression" else 1 if row["ended_at"] is None else 0,
               row.get("_chain_activity") or 0, row["started_at"], row["id"])
        if parent not in chosen or key > chosen[parent][0]:
            chosen[parent] = key, row["id"]
    return {parent: value[1] for parent, value in chosen.items()}

import hashlib

def _bytes(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": bytes(value).hex()}
    raise TypeError(f"Unsupported move snapshot value: {type(value).__name__}")

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=_bytes).encode()).hexdigest()

def resource_key(transactions):
    url = transactions.engine.url
    endpoints = {name: value for name, value in url.query.items() if name in ("host", "hostaddr", "port", "dbname", "database", "service")}
    return digest([url.drivername, url.host, url.port, url.database, endpoints, transactions.schema])
