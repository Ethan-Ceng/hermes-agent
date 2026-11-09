"""Detached attempt evidence for recovery policy and subsequent under-lock validation."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TaskEvidence:
    task: Mapping
    run: Mapping
    payloads: Mapping
    event_watermark: int


def typed_owner_receipt(payload):
    """New PG datasets require an explicit selected owner, never a legacy file pointer."""
    if payload is None:
        return None
    if payload.get("storage_backend") not in {"sqlite", "postgresql"}:
        return {}
    if not all(isinstance(payload.get(key), str) and payload[key] for key in ("profile_home", "principal_id")):
        return {}
    if payload["storage_backend"] == "postgresql" and not all(
            isinstance(payload.get(key), str) and payload[key] for key in ("store_id", "target")):
        return {}
    return payload
