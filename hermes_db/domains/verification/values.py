"""Evidence DTO, time encoding and retention limits shared by storage backends."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, UTC

_MAX_EVIDENCE_AGE_DAYS = 30

_MAX_EVENTS_PER_SESSION_ROOT = 100

_MAX_TOTAL_UNREFERENCED_EVENTS = 10_000

@dataclass(frozen=True)
class VerificationEvidence:
    """A classified command result worth recording."""

    command: str
    canonical_command: str
    kind: str
    scope: str
    status: str
    exit_code: int
    cwd: str
    root: str
    session_id: str
    output_summary: str = ""

def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

VerificationEvidence.__module__ = "agent.verification_evidence"
