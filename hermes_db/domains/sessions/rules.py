"""Pure title sanitization and persisted gateway-route projection shared by session backends."""
from __future__ import annotations
import re
from agent.message_sanitization import _sanitize_surrogates
from typing import Optional, Any
import json
_TITLE_CONTROL_RE = re.compile('[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]')
_TITLE_INVISIBLE_RE = re.compile('[\\u200b-\\u200f\\u2028-\\u202e\\u2060-\\u2069\\ufeff\\ufffc\\ufff9-\\ufffb]')

def sanitize_title(title: Optional[str], *, max_length=100) -> Optional[str]:
    """Strip control/zero-width/bidi chars (and lone surrogates sqlite3 cannot bind),
        collapse whitespace, normalize empty to None. ValueError past MAX_TITLE_LENGTH."""
    if not title:
        return None
    cleaned = _TITLE_INVISIBLE_RE.sub('', _TITLE_CONTROL_RE.sub('', _sanitize_surrogates(title)))
    cleaned = re.sub('\\s+', ' ', cleaned).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f'Title too long ({len(cleaned)} chars, max {max_length})')
    return cleaned
_BARE_BILLING_PROVIDERS = frozenset({'auto', 'custom'})

def session_gateway_runtime(session_meta: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Read the persisted runtime route off a session row dict (``model_config`` as
        JSON string or parsed dict). Precedence: nested ``gateway_runtime`` (gateway sync /
        CLI ``/model``), then top-level ``provider``/``base_url``/``api_mode`` (TUI), with
        ``billing_provider`` filling a missing provider so sessions that never ran ``/model``
        still restore the provider that served them; a bare ``custom`` billing class falls back
        to its ``billing_base_url`` endpoint for the readers' bare-custom heal (#136323).
        Empty dict on parse failure — resume uses ambient config."""
    raw = (session_meta or {}).get('model_config')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # health: allow BLE001 -- preserve the legacy ambient-route fallback for optional persisted metadata
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    runtime = raw.get('gateway_runtime')
    if isinstance(runtime, dict) and runtime.get('provider'):
        return {k: v for k, v in runtime.items() if v is not None}
    top_level = {key: raw.get(key) for key in ('provider', 'base_url', 'api_mode') if raw.get(key)}
    billing_provider = str((session_meta or {}).get('billing_provider') or '').strip()
    if billing_provider and billing_provider.lower() not in _BARE_BILLING_PROVIDERS:
        top_level.setdefault('provider', billing_provider)
    elif billing_provider.lower() == 'custom' and (not top_level.get('provider')):
        billing_base_url = str((session_meta or {}).get('billing_base_url') or '').strip()
        if billing_base_url:
            top_level.setdefault('base_url', billing_base_url)
            top_level['provider'] = 'custom'
    if top_level:
        return top_level
    if not isinstance(runtime, dict):
        return {}
    return {k: v for k, v in runtime.items() if v is not None}

import logging
logger = logging.getLogger("hermes_state")

def _json_or(raw: Any, fallback: Any, warning: str) -> Any:
    """``json.loads(raw)``; on failure log *warning* and return *fallback*."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(warning)
        return fallback

from agent.skill_commands import describe_skill_invocation, SKILL_EXCERPT_JOINT

_PREVIEW_MAX_CHARS = 60

QUEUED_PROMPT_METADATA_KEY = "_queued_prompt"

def _shape_preview(raw: Any) -> str:
    """Turn a ``_preview_raw`` column into the short preview callers show."""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", " ")
    described = describe_skill_invocation(text)
    text = described if described is not None else text.split(SKILL_EXCERPT_JOINT)[0]
    return text[:_PREVIEW_MAX_CHARS] + "..." if len(text) > _PREVIEW_MAX_CHARS else text

_RESET_END_REASONS = ("session_reset", "session_switch", "idle", "daily", "suspended", "resume_pending_expired")

_BOUNDARY_END_REASONS = frozenset(_RESET_END_REASONS) | {"new_session"}

_RECOVERABLE_END_REASONS = ("agent_close", "ws_orphan_reap", "superseded_by_resume", "startup_orphan_reap")

_AUTOMATIC_END_REASONS = frozenset(_RECOVERABLE_END_REASONS) | {
    "tui_shutdown", "ws_disconnect", "idle_timeout", "lru_evict"}

def is_automatic_end_reason(reason) -> bool:
    """True when *reason* is an automatic-cleanup end stamp; compression-liveness sites must call this.

    Single owner of the "accidental vs deliberate end" predicate — every compression-liveness site must call
    this instead of re-implementing the reason taxonomy (#88197, never-patch-predicates).
    """
    return isinstance(reason, str) and reason in _AUTOMATIC_END_REASONS

FTS_TOOL_CONTENT_PREFIX_CHARS = 8_192

MAX_FTS5_QUERY_CHARS = 2_048

FTS_TRIGRAM_EXCLUDED_SOURCES = ("cron", "subagent")

INTERNAL_LISTING_SOURCES = ("kanban", "tool", "oneshot")

SESSION_STATUS_COMPLETE = "complete"

SESSION_STATUS_INTERRUPTED = "interrupted"

SESSION_STATUS_ERROR = "error"

_ERROR_FINISH_REASONS = frozenset({"error", "agent_error", "content_filter"})

def classify_session_status(role: Optional[str], has_tool_calls: bool, finish_reason: Optional[str]) -> str:
    """Error finish → ``error``; assistant with pending tool_calls or a trailing user/tool row →
    ``interrupted``; otherwise ``complete`` (benign default: pickers must not alarm on unknown shapes)."""
    if (finish_reason or "").strip().lower() in _ERROR_FINISH_REASONS:
        return SESSION_STATUS_ERROR
    r = (role or "").strip().lower()
    if r in {"user", "tool"} or (r == "assistant" and has_tool_calls):
        return SESSION_STATUS_INTERRUPTED
    return SESSION_STATUS_COMPLETE

def bot_chat_title_released(archived: Any, auto_archived: Any, tip_end_reason: Optional[str]) -> bool:
    """The ONE predicate for "this archived row titled "Bot Chat" no longer holds the name"
    (#139779): deliberately archived, i.e. not by the idle sweep (``auto_archived``, which
    re-activation undoes) and without a recoverable reaper stamp on the lineage tip (#92687
    resurrects those). Hidden or visible alike: a Bot Chat the delivery door minted is visible.
    The title lookup skips exactly the rows the title-conflict check frees, so a lookup that says
    "absent" never meets a name it cannot take."""
    return bool(archived) and not auto_archived and (tip_end_reason or "") not in _RECOVERABLE_END_REASONS

PROFILE_KEY = "prompt_refresh.epoch"

SESSION_KEY_PREFIX = "prompt_refresh.epoch:"

_TOKEN_COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")

_MODEL_USAGE_FIELDS = frozenset((
    "model", "billing_provider", "billing_base_url", "billing_mode", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "estimated_cost_usd",
    "actual_cost_usd", "cost_status", "cost_source", "api_call_count"))

_NUMBERED_TITLE_RE = re.compile(r'^(.*?) #(\d+)$')

# State-owned producers only; messaging/UI lifecycles and unknown sources stay excluded.
AUTO_PRUNE_STALE_OPEN_SOURCES = (
        "cli", "cron", "kanban", "acp", "api_server", "subagent", "tool", "recovered",
    )
