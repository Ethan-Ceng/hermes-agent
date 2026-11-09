"""Canonical runtime refusal, receipt identity and row projections shared by both backends."""
import hashlib
import math
import json
from dataclasses import dataclass
from typing import NamedTuple
from agent.conversation_compression_archive import ABSORBED_ROW_IDS
from agent.message_metadata import (CANONICAL_ROW, DATA_USE, DB_ROW_SNAPSHOT, MESSAGE_UID,
    PERSISTENCE_ONLY_MESSAGE_FIELDS, TOOL_CALL_UID, TOOL_CALL_UIDS)
from hermes_state_keys import admission_fingerprint

class SessionGoneEvent(NamedTuple):
    """The ``on_session_delete`` event a committed runtime mutation owes its plugins."""
    session_ids: tuple
    reason: str

class RuntimeStoreError(ValueError):
    """A refusal by the state authority. ``reason`` is the bounded wire code (callers compare it as a
    string); ``field`` and ``detail`` name the check that fired and why, so a client and the gateway
    log can tell the reasons' many checks apart instead of reporting the bare code."""

    def __init__(self, reason: str, *, field: str | None = None, detail: str | None = None):
        self.reason = reason
        self.field = _one_line(field, 80)
        self.detail = _one_line(detail, 160)
        super().__init__(reason)

ADMITTED_REQUEST_CONFLICT = {'field': 'request_id', 'detail': 'this request id was already admitted with another payload'}

def _one_line(value, limit):
    """A refusal's ``field``/``detail`` as the log line and the client frame carry it: either may hold
    client text, so whitespace collapses to single spaces, other non-printables drop (no forged log
    lines), and the length is bounded below the client's frame limit."""
    if value is None:
        return None
    text = ''.join(ch for ch in ' '.join(str(value).split()) if ch.isprintable())
    return text[:limit] or None

def _text(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise RuntimeStoreError('invalid_params')
    return value

def _json(value):
    if not isinstance(value, dict):
        raise RuntimeStoreError('invalid_params')
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RuntimeStoreError('invalid_params') from exc

ADMISSION_QUEUE_MAX = 32

def mutation_receipt_key(principal_id, session_id, request_id, *, operation, payload, expected_revision,
                         expected_generation=None):
    """``(state_meta key, digest)`` of a mutation request's durable exact-retry receipt."""
    key = 'gateway.mutation.v1.' + admission_fingerprint(
        canonical_target=session_id, payload={'principal': principal_id, 'request': request_id})
    fingerprint = {'operation': operation, 'payload': payload, 'expected_revision': expected_revision}
    if expected_generation is not None:
        fingerprint['expected_generation'] = expected_generation
    return key, admission_fingerprint(canonical_target=session_id, payload=fingerprint)

def _secret_digest(secret):
    import hashlib
    _text(secret)
    return hashlib.sha256(secret.encode('utf-8')).hexdigest()

_MESSAGE_FIELDS = frozenset({
    'role', 'content', 'tool_name', 'tool_calls', 'tool_call_id', 'token_count',
    'finish_reason', 'reasoning', 'reasoning_content', 'reasoning_details',
    'codex_reasoning_items', 'codex_message_items', 'platform_message_id', 'message_id',
    'observed', 'effect_disposition', '_compressed_summary', 'timestamp', 'api_content',
    'display_kind', 'display_metadata', '_row_id', '_canonical_content', DB_ROW_SNAPSHOT, CANONICAL_ROW, DATA_USE,
    # Main's durable message identity (message_uid / merge witness / tool-call uids) and the alternation
    # repair's row counts ride every persisted dict; the owner's insert and coverage read them.
}) | PERSISTENCE_ONLY_MESSAGE_FIELDS | {ABSORBED_ROW_IDS}

HANDOFF_MESSAGE_FIELDS = _MESSAGE_FIELDS | {'_compressed_summary_has_user_turn'}

_ROW_ANNOTATION_KEYS = ('_row_id', 'timestamp', DB_ROW_SNAPSHOT, CANONICAL_ROW,
                        MESSAGE_UID, TOOL_CALL_UIDS, TOOL_CALL_UID)

def row_annotations(messages):
    return [{key: msg.get(key) for key in _ROW_ANNOTATION_KEYS} for msg in messages]

# These are established public values. Keep their import/pickle identity at the public Native API.
SessionGoneEvent.__module__ = "hermes_state_runtime"
RuntimeStoreError.__module__ = "hermes_state_runtime"

SIDECAR_KEYS = frozenset({'_usage_anchor', '_proactive_prune_rearm_tokens', '_anthropic_rejected_thinking'})

_IDENTITY_FIELDS = frozenset({
    'user_id', 'session_key', 'chat_id', 'chat_type', 'thread_id',
    'parent_session_id', 'cwd', 'profile_name', 'git_repo_root', 'origin_json', 'display_name',
})

_CREATE_FIELDS = _IDENTITY_FIELDS | {'source', 'model', 'model_config', 'system_prompt'}

_CONSTRUCTOR_CONFIG = frozenset({'max_iterations', 'max_tokens', 'reasoning_config', 'yolo_mode'})

def _row_id(payload):
    row_id = payload.get('row_id')
    if type(row_id) is not int or row_id <= 0:
        raise RuntimeStoreError('invalid_params')
    return row_id

def api_generation_id(session_id, generation):
    """Generation *generation* of an API session id ``implicit_api_session`` walks: the id itself,
    then ``api-<digest(id, n)>``."""
    if not generation:
        return session_id
    return 'api-' + hashlib.sha256(f'{session_id}\0{generation}'.encode()).hexdigest()[:16]

DELEGATION_TASK_KEYS = {'goal', 'goals', 'context', 'toolsets', 'role', 'model', 'is_batch', 'task_indexes'}

DELEGATION_ROUTE = {'session_key': 'origin_session', 'parent_session_id': 'parent_session_id',
          'origin_ui_session_id': 'origin_ui_session_id', 'origin_session_id': 'origin_session_id'}

DELEGATION_EVENT_KEYS = DELEGATION_TASK_KEYS | set(DELEGATION_ROUTE) | {
    'type', 'delegation_id', 'status', 'completed_at', 'dispatched_at', 'summary', 'error',
    'api_calls', 'duration_seconds', 'total_duration_seconds', 'results', 'live_transcripts',
    'group', 'exit_reason', 'stalled_after_quiet_seconds', 'stall_threshold_seconds',
    'stall_phase', 'stall_grace_seconds'}

def delegation_shape(payload, keys):
    if not isinstance(payload, dict) or set(payload) != set(keys):
        raise RuntimeStoreError('invalid_params')

def delegation_text(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RuntimeStoreError('invalid_params')

def delegation_number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise RuntimeStoreError('invalid_params')

@dataclass(frozen=True)
class VerifiedDelegationOwner:
    execution_id: str
    pid: int
    birth: float
    started_at: int | None

VerifiedDelegationOwner.__module__ = "hermes_db.domains.runtime.postgres.operations.worker_delegations"
