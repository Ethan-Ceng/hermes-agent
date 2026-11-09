"""Backend-independent runtime receipt values and exact-retry projections."""
from __future__ import annotations
from typing import Any
import json
from hermes_db.domains.runtime.values import RuntimeStoreError
from hermes_state_keys import admission_fingerprint

POLICY_PREFIX = 'gateway.local_policy.v1:'

API_BINDING_PREFIX = 'gateway.api.binding.v1.'

API_DECLARED_PREFIX = 'gateway.api.conversation.v1.'

def client_request(request_json, derived=None):
    """A frozen create request as the client sent it: an owner-resolved ``-m`` route (``model_requested``)
    compares by the name the client typed, not by the model and the *derived* fields (a receipt from
    before ``route_derived``: the endpoint) its ``${VAR}`` refs expanded to at the time. ``desktop_local``
    (``gateway.session_policy.LOCAL_DESKTOP_CHAT``), which an earlier owner stamped into the request, was
    never sent."""
    request = json.loads(request_json)
    request.pop('desktop_local', None)
    if derived is None:
        request.pop('route_derived', None)
    if 'model_requested' in request:
        request.pop('model', None)
        for key in ('base_url',) if derived is None else derived:
            request.pop(key, None)
    return request

def same_create_request(saved_json, retry_json):
    """Whether a create retry carries the frozen request it resumes: one check for a retry that finds the
    session committed and one staged before it was. The saved receipt's provenance names the owner's
    fields; one from before a same-name alias got ``model_requested`` compares exactly, as it did."""
    derived = json.loads(saved_json).get('route_derived')
    if client_request(saved_json, derived) == client_request(retry_json, derived):
        return True
    retry = json.loads(retry_json)
    if retry.get('model_requested') == retry.get('model'):
        retry.pop('model_requested', None)
        retry.pop('route_derived', None)
    return json.loads(saved_json) == retry

def same_create_retry(saved_policy, retry_json, client_request):
    """The one exact-retry identity of a create: ``same_create_request`` on what the client sent, and its
    ``client_env`` (``client_request``: the retry's own, never stored) judged by the rules frozen with
    *saved_policy*. Used by a retry that finds the session committed, at commit, and by one overlapping
    the attempt that holds the session's key slot."""
    from agent.session_client_env import retry_matches
    return same_create_request(saved_policy['request_json'], retry_json) and retry_matches(saved_policy, client_request)

def _row_cwd(policy):
    """The sessions-row ``cwd``: the create request's ``row_cwd`` (``""`` = none) when it sent one,
    else the execution cwd. Row metadata only (workspace grouping, ``-c``, cwd restore); the
    frozen policy's ``cwd`` / ``TERMINAL_CWD`` stay where the session's tools run."""
    try:
        request = json.loads(policy.get('request_json') or '{}')
    except (TypeError, ValueError):
        request = {}
    value = request.get('row_cwd') if isinstance(request, dict) else None
    return policy['cwd'] if not isinstance(value, str) else (value or None)

def _policy_target(raw):
    """Current physical target a creation receipt routes to; None for a malformed receipt, which
    then stays (its own reads already refuse it as ``storage_unavailable``) and cannot abort
    the delete of an unrelated session."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    entry = value.get('entry') if isinstance(value, dict) else None
    return entry.get('session_id') if isinstance(entry, dict) else None

RESULT_PREFIX = 'gateway.admission.result.v1.'

ADMISSION_PREFIX = 'gateway.terminal_admission.v1.'

IDENTITY_PREFIX = 'gateway.terminal_identity.v1.'

WORKER_PREFIX = 'gateway.terminal_worker.v1.'

def compact_result(result, *, user_message=None):
    """Retain replay/accounting and current-turn API output, never cumulative history."""
    result = dict(result)
    value = result.get('result')
    if not isinstance(value, dict):
        return result
    value = dict(value)
    # The tool schema list rides every turn result for in-process transcript logging; it is the
    # same session-wide copy each turn (tens of KB, more with MCP) and no stored-result reader uses it.
    value.pop('tools', None)
    messages = value.get('messages')
    if isinstance(messages, list):
        # Agent results include all previous turns. APIs only project this turn's
        # assistant/tool suffix; previous_response_id stores its own history. Compression
        # is the exception: its replacement snapshot is the only immutable record of the
        # rewritten prefix for this turn. A later live transcript may include a successor.
        if not value.get('_compressed') and not value.get('_messages_are_turn_suffix'):
            from agent.turn_context import reanchor_current_turn_user_idx
            anchor = value.get('current_turn_user_idx')
            if not (type(anchor) is int and 0 <= anchor < len(messages)
                    and isinstance(messages[anchor], dict) and messages[anchor].get('role') == 'user'):
                anchor = reanchor_current_turn_user_idx(messages, user_message)
            value['messages'] = messages[anchor + 1:]
            if anchor >= 0 and isinstance(messages[anchor], dict) and messages[anchor].get('api_content'):
                # The user row as the model saw it (memory prefetch, plugin context): a chained
                # Responses turn replays it instead of a row rebuilt from the raw request text.
                value['_turn_user_row'] = {k: messages[anchor][k] for k in ('role', 'content', 'api_content')}
            # Recovery/verification nudges are later user-role rows within this same turn.
            # Consumers must not infer a new boundary from them after the real anchor is gone.
            value['_messages_are_turn_suffix'] = True
            value.pop('current_turn_user_idx', None)
    result['result'] = value
    return result

_STORED = '_stored'

def encode_result(result):
    """The stored row keeps the reply once. When the turn's closing assistant message carries
    exactly ``final_response``, its ``content`` is stored as null and the row gets
    ``_stored: {v: 1, reply_ref: <that message's index>}``. Retirement drops ``messages`` and
    keeps ``final_response``, so a deleted session's exact retry still has its reply. A result
    that already has ``_stored`` is stored whole with that value escaped as ``{v: 1, raw: ...}``."""
    if not isinstance(result, dict):
        return result
    if _STORED in result:
        return {**result, _STORED: {'v': 1, 'raw': result[_STORED]}}
    value = result.get('result')
    if not isinstance(value, dict) or not isinstance(value.get('messages'), list):
        return result
    reply, messages = value.get('final_response'), list(value['messages'])
    last = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], dict)
                 and messages[i].get('role') == 'assistant'), None)
    if not (isinstance(reply, str) and reply and last is not None and messages[last].get('content') == reply):
        return result
    messages[last] = {**messages[last], 'content': None}
    return {**result, 'result': {**value, 'messages': messages}, _STORED: {'v': 1, 'reply_ref': last}}

def load_result(text):
    """Decode a stored result row. Only a row carrying ``encode_result``'s exact envelope is
    decoded (to the dict it encoded, key order included); every other row, including all rows
    written before it, is returned as stored."""
    # Decodes in place: safe only because each call parses its own copy. A cache in front of this
    # must hand out copies, never the decoded dict itself.
    result = json.loads(text)
    if not isinstance(result, dict) or not isinstance(envelope := result.get(_STORED), dict):
        return result
    if envelope.keys() == {'v', 'raw'} and type(envelope['v']) is int and envelope['v'] == 1:
        result[_STORED] = envelope['raw']
        return result
    value, ref = result.get('result'), envelope.get('reply_ref')
    messages = value.get('messages') if isinstance(value, dict) else None
    if not (envelope.keys() == {'v', 'reply_ref'} and type(envelope['v']) is int and envelope['v'] == 1
            and type(ref) is int and isinstance(messages, list) and 0 <= ref < len(messages)
            and isinstance(value.get('final_response'), str) and isinstance(messages[ref], dict)
            and messages[ref].get('role') == 'assistant' and messages[ref].get('content', 0) is None):
        return result
    messages[ref] = {k: value['final_response'] if k == 'content' else v for k, v in messages[ref].items()}
    del result[_STORED]
    return result

def identity_key(principal_id, session_id, request_id):
    return IDENTITY_PREFIX + admission_fingerprint(canonical_target=session_id,
        payload={'principal': principal_id, 'request': request_id})

RETIRED_PREFIX = 'gateway.retired_session.v1.'

ROUTE_FENCE_PREFIX = 'gateway.retired_route.v1.'

VIEWER_CLOSE_PREFIX = 'gateway.viewer_close.v1:'

def entry_session_id(raw):
    """The ``session_id`` a stored routing/receipt JSON object names, else None. Unrelated rows
    are not validated here: a malformed one (an array, invalid JSON) names no target, so it can
    neither be retired nor abort the delete of a different session; the routing loader skips it too."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value.get('session_id') if isinstance(value, dict) else None

def route_namespace(session_key):
    """The ``<ns>`` slot of an ``agent:<ns>:...`` routing key (``main`` for the launch profile, else
    the profile's ``_session_key_namespace`` slot); ``main`` for a key outside that shape."""
    parts = str(session_key or '').split(':')
    return parts[1] if len(parts) > 2 and parts[0] == 'agent' and parts[1] else 'main'

def route_fence_key(namespace, session_id):
    return f'{ROUTE_FENCE_PREFIX}{namespace}:{session_id}'

RETRY_HORIZON_S = 7 * 86400  # exact-retry horizon: a retry within it gets the byte-exact settled reply

RETIRED_RECEIPT = {'retired': True}

CHILD_SEPARATOR = '/child:'

def retired_receipt(result_json):
    return json.loads(result_json) == RETIRED_RECEIPT

DEFERRED_PICK_PREFIX = 'gateway.deferred_pick.v1.'

RETIRED_MEDIA_PREFIX = 'gateway.media.retired.v1.'
MEDIA_SPILLOVER_PREFIX = 'gateway.spillover.retired.v1.'

BINDING_PREFIX = 'gateway.history_control.v1.'

API_RUN_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})

CLOSED_RUN_FINGERPRINT = "closed"

def encode_run_status(status: dict[str, Any]) -> str:
    return json.dumps(status, sort_keys=True, separators=(",", ":"))

def run_identity_record(run_id, status_json, owner_pid, owner_started, updated_at) -> dict[str, Any]:
    return {
        "run_id": run_id, "status": json.loads(status_json), "owner_pid": int(owner_pid or 0),
        "owner_started": int(owner_started or 0), "updated_at": float(updated_at or 0)}

def deferred_value(current, operation, pick, shown):
    if operation == 'reasoning':
        current.get('payload', {}).pop('reasoning', None)
        return {**current, 'reasoning': pick}, {'effort': pick['payload']['effort']}
    older = 'reasoning' in current and 'reasoning' not in pick['payload']
    return {**pick, **({'reasoning': current['reasoning']} if older else {})}, {'model': shown or pick['payload']['model']}

def automation_descriptor(payload):
    return payload.get('local_automation_v1') or (payload.get('native_text_v1') or {}).get('automation') or {}

FOLDED_AUTOMATION_TEXT = '[folded into a later completion batch]'
