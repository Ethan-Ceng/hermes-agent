"""Pure title sanitization and persisted gateway-route projection shared by session backends."""
from __future__ import annotations
from agent.message_sanitization import _sanitize_surrogates
from typing import Optional, Any
import re
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
