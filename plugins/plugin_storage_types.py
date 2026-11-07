"""Driver-free, portable plugin JSON records and concurrency contracts."""

from dataclasses import dataclass
import json
import math
from typing import Any, Protocol

MAX_VALUE_BYTES = 1024 * 1024
MAX_NAMESPACE_BYTES = 16 * 1024 * 1024
MAX_NAMESPACE_KEYS = 4096


class PluginStorageConflict(RuntimeError):
    """The expected record revision no longer exists."""


class PluginStorageQuotaError(ValueError):
    """A bounded plugin namespace cannot retain this value."""


@dataclass(frozen=True)
class PluginRecord:
    key: str
    value: Any
    revision: int
    expires_at: float | None


class PluginStore(Protocol):
    def get(self, key: str) -> PluginRecord | None: ...
    def put(self, key: str, value: Any, *, expected_revision: int | None = None, ttl_seconds: float | None = None) -> PluginRecord: ...
    def delete(self, key: str, *, expected_revision: int | None = None) -> bool: ...
    def scan(self, *, after: str | None = None, prefix: str = "", limit: int = 100) -> list[PluginRecord]: ...
    def prune_expired(self, *, limit: int = 200) -> int: ...


def validate_key(key, *, empty=False):
    if not isinstance(key, str) or (not key and not empty) or len(key.encode("utf-8")) > 512:
        raise ValueError("Plugin storage keys must be UTF-8 strings of 1–512 bytes")
    return key.encode("utf-8")


def validate_revision(revision):
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision < 0):
        raise ValueError("Expected plugin revision must be a non-negative integer or None")


def validate_json(value, depth=0):
    if depth > 32:
        raise ValueError("Plugin JSON nesting exceeds 32 levels")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Plugin JSON object keys must be strings")
        for item in value.values():
            validate_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            validate_json(item, depth + 1)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("Plugin values must use JSON types")


def encode_value(value):
    validate_json(value)
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_VALUE_BYTES:
        raise PluginStorageQuotaError("Plugin value exceeds 1 MiB")
    return data


def validate_ttl(ttl):
    if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0):
        raise ValueError("Plugin TTL must be a finite positive number of seconds")


def validate_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("Plugin page limit must be between 1 and 200")


def check_revision(row, expected):
    if expected is not None and ((0 if row is None else row["revision"]) != expected):
        raise PluginStorageConflict("Plugin record revision changed; read the current record before retrying")


def decode_record(row):
    return None if row is None else PluginRecord(bytes(row["key"]).decode("utf-8"), json.loads(bytes(row["value"])), int(row["revision"]), row["expires_at"])
