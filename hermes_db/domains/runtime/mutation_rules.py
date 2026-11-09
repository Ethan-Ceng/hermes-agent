"""Closed mutation payload validation shared by both runtime backends."""
from hermes_db.domains.runtime.values import RuntimeStoreError

METADATA_FIELDS = {'title': str, 'archived': bool, 'hidden': bool, 'pinned': bool, 'unread': bool}

def validate_action(operation, payload):
    if not isinstance(payload, dict) or not isinstance(operation, str):
        raise RuntimeStoreError('invalid_params')
    # ``confirm``: the owner's selection-guard token for this exact resolved target (session_mutation_model).
    # ``reasoning``: a level picked with the model, committed in the same selection.
    if (operation == 'model' and 'model' in payload and not set(payload) - {'model', 'provider', 'confirm', 'reasoning'}
            and all(isinstance(v, str) and v.strip() for v in payload.values())):
        from hermes_constants import parse_reasoning_effort
        if 'reasoning' not in payload or parse_reasoning_effort(payload['reasoning']) is not None:
            return
    if operation == 'branch' and _valid_branch_payload(payload):
        return
    # Session-scope ``/reasoning <level>`` and Desktop's Move to project: revision-fenced edits of
    # the frozen policy (gateway/session_mutation_policy.py).
    if operation == 'reasoning' and set(payload) == {'effort'} and payload['effort'] is None:
        return  # ``/reasoning reset``: the session's level goes back to the profile
    if operation == 'reasoning' and set(payload) == {'effort'} and isinstance(payload['effort'], str):
        from hermes_constants import parse_reasoning_effort
        if parse_reasoning_effort(payload['effort']) is not None:
            return
    if operation == 'workspace' and set(payload) == {'cwd'} and isinstance(payload['cwd'], str) and payload['cwd'].strip():
        return
    # The editor's MCP servers (gateway/session_local_mcp.py): the owner keeps the list in memory and
    # hands the store only its fingerprint, so no transport credential reaches a receipt.
    if operation == 'editor_mcp' and set(payload) == {'mcp_servers'} and _valid_editor_fingerprint(payload):
        return
    # An ACP session's edit approval policy (gateway/session_mutation_policy.py prepare_edit_policy).
    if (operation == 'edit_policy' and set(payload) == {'policy'} and isinstance(payload['policy'], str)
            and payload['policy'] in {'ask', 'workspace_session', 'session'}):
        return
    if operation == 'compress' and _valid_compress_payload(payload):
        return
    if operation in {'delete', 'reset'} and not payload:
        return
    if operation == 'import' and set(payload) == {'sessions'} and isinstance(payload['sessions'], list):
        return
    if (operation == 'rewind' and 'target_message_id' in payload
            and not set(payload) - {'target_message_id', 'preserve_compaction_handoff'}
            and type(payload['target_message_id']) is int and payload['target_message_id'] > 0
            and type(payload.get('preserve_compaction_handoff', False)) is bool):
        return
    required = {'rename': {'title'}, 'archive': {'archived'}}
    if operation == 'sidebar':
        valid = bool(payload) and not set(payload) - METADATA_FIELDS.keys()
    else:
        valid = operation in required and set(payload) == required[operation]
    if not valid or any(type(value) is not METADATA_FIELDS[key] for key, value in payload.items()):
        raise RuntimeStoreError('invalid_params')

def _valid_branch_payload(payload):
    # ``through_message_id``: the physical row id of the last message the branch keeps (a stable
    # boundary, never a visible-message count); absent means the whole active transcript.
    if set(payload) - {'title', 'through_message_id', 'mcp_servers'}:
        return False
    if 'mcp_servers' in payload and not _valid_editor_fingerprint(payload):
        return False
    if 'title' in payload and not isinstance(payload['title'], str):
        return False
    return 'through_message_id' not in payload or (
        type(payload['through_message_id']) is int and payload['through_message_id'] > 0)

def _valid_editor_fingerprint(payload):
    servers = payload['mcp_servers']
    return isinstance(servers, dict) and set(servers) == {'fingerprint'} and isinstance(servers['fingerprint'], str)

_COMPRESS_FIELDS = {'focus': str, 'preview': bool, 'partial': bool, 'keep_last': int}

def _valid_compress_payload(payload):
    # ``focus`` alone may still be the raw ``/compress`` argument string (Ink/Desktop
    # clients); the structured flags come from the shared parser on the native CLI/ACP path.
    if set(payload) - _COMPRESS_FIELDS.keys():
        return False
    if any(type(value) is not _COMPRESS_FIELDS[key] for key, value in payload.items()):
        return False
    return 'keep_last' not in payload or (payload.get('partial') is True and payload['keep_last'] >= 1)

COMPACTED_TARGET_DETAIL = 'compacted: target user message was summarized when the session was compressed'

def _child_policy(policy, child, prepared):
    """The parent's frozen policy, except editor MCP servers: the gateway prepared the child's own
    selection under the child's own scope (gateway/session_local_mcp.py ``prepare_branch_editor``).
    Copying the parent's would share its scope, borrowed credentials and live connections.
    A branch starts at Default (``ask``), as main's ACP ``fork_session`` did."""
    if 'edit_approval_policy' in policy:
        policy = {**policy, 'edit_approval_policy': 'ask'}
    if prepared is None:
        if policy.get('editor_mcp_json'):
            raise RuntimeStoreError('runtime_coordination_required')
        return policy
    # Prepared against the parent's selection and the child id this commit derives; anything else moved.
    if child != prepared['child'] or policy.get('editor_mcp_json') != prepared['parent_editor_mcp_json']:
        raise RuntimeStoreError('revision_conflict')
    return {**policy, 'editor_mcp_json': prepared['editor_mcp_json'], 'toolsets': prepared['toolsets'],
            'config_secret_ref': prepared['config_secret_ref']}
