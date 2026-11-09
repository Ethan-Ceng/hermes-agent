"""Closed action handlers inside the runtime mutation receipt transaction."""
import time
from hermes_state_runtime import RuntimeStoreError
from hermes_db.domains.runtime.mutation_rules import COMPACTED_TARGET_DETAIL













def apply_action(db, conn, session_id, operation, payload, *, prepared=None):
    if operation == 'compress':
        from hermes_state_mutation_compress import compress_in_transaction
        return compress_in_transaction(db, conn, session_id, payload, prepared)
    if operation in {'model', 'reasoning', 'workspace', 'editor_mcp', 'edit_policy'}:
        from hermes_state_mutation_prepared import POLICY_HANDLERS
        return POLICY_HANDLERS[operation](db, conn, session_id, payload, prepared)
    if operation == 'branch':
        from hermes_state_mutation_branch import branch_in_transaction
        return branch_in_transaction(db, conn, session_id, payload, prepared)
    from hermes_state_mutation_reset import reset_in_transaction
    handlers = {'delete': _delete, 'import': _import, 'rewind': _rewind, 'reset': reset_in_transaction}
    if operation in handlers:
        return handlers[operation](db, conn, session_id, payload)
    affected = set()
    result = {}
    for key, value in payload.items():
        if key == 'title':
            affected.update(db._set_session_title_in_transaction(
                conn, session_id, value, source=db.TITLE_SOURCE_USER))
            result[key] = conn.execute('SELECT title FROM sessions WHERE id=?', (session_id,)).fetchone()[0]
        else:
            column = 'last_read_at' if key == 'unread' else key
            stored = (0.0 if value else time.time()) if key == 'unread' else int(value)
            affected.update(db._set_lineage_column_in_transaction(conn, column, session_id, stored))
            if key == 'archived' and value:
                # Desktop's Archive lands here, not in set_session_archived: same retire (#139779).
                affected.update(db._retire_canonical_bot_chat_in_transaction(conn, session_id))
            result[key] = value
    return affected, result


def _delete(db, conn, session_id, payload):
    # Terminal admission/worker rows become digest tombstones so exact retries and
    # adoption checks still resolve after the transcript is gone.
    from hermes_state_mutation_retirement import delete_in_transaction
    return delete_in_transaction(db, conn, session_id, payload)


def _rewind(db, conn, session_id, payload):
    from hermes_state_mutation_guards import require_idle
    from hermes_state_mutation_transcript import rewind_in_transaction
    from hermes_state_local_lineage import local_physical_target
    physical = local_physical_target(conn, session_id)
    require_idle(db, conn, list({session_id, physical}))
    # The client names the row: like a branch boundary it must be an active row of the physical
    # target. A row compaction archived (still shown, still carrying its id) would deactivate the
    # summary and every later turn, since both have larger ids. That refusal says so (``compacted:``
    # detail); a row a rewind or undo already took back, an assistant row or an unknown id does not.
    row = conn.execute('SELECT role FROM messages WHERE id=? AND session_id=? AND active=1',
                       (payload['target_message_id'], physical)).fetchone()
    if row is None or row['role'] != 'user':
        if _summarized_by_compaction(conn, physical, payload['target_message_id']):
            raise RuntimeStoreError('invalid_params', field='target_message_id', detail=COMPACTED_TARGET_DETAIL)
        raise RuntimeStoreError('invalid_params', field='target_message_id',
                                detail='target user message is no longer in session history')
    # A composite compaction carrier (summary + the next ask in one row) keeps its handoff, as
    # main's rewind does; the receipt reports the live ask, so /retry resubmits it, not the summary.
    live = _carrier_live_view(db, conn, physical, payload['target_message_id'])
    target, ids, head, replacement = rewind_in_transaction(db, conn, physical, payload['target_message_id'],
        preserve_compaction_handoff=live is not None or payload.get('preserve_compaction_handoff', False))
    # Receipts are JSON: publish the same public message shape get_messages() returns (decoded
    # content/tool_calls, no internal display_identity BLOB / display_order).
    target = db._row_to_message_dict(target, warn_context='rewind receipt', summary_flag=True)
    if live is not None:
        target['content'] = live.get('content')
    from agent.message_metadata import typed_prompt_content  # /retry, /undo: the typed ask, not the placeholder
    target['content'] = typed_prompt_content(target.get('content'), target)
    conn.execute('UPDATE sessions SET runtime_generation=runtime_generation+1 WHERE id=?', (session_id,))
    return {session_id, physical}, {'rewound_count': len(ids), 'target_message': target,
        'new_head_id': head, 'replacement_message_id': replacement}


# The refusal's ``detail`` for a target compaction summarized: ``compacted:`` is the machine-readable
# prefix clients match (Desktop's restore/edit toast); the rest is the log line.


def _summarized_by_compaction(conn, physical, message_id):
    """Whether *message_id* is a user turn compaction took out of *physical*'s live transcript, as
    opposed to one a rewind/undo deactivated, an assistant row, or no row at all. In-place compaction
    archives with ``active=0, compacted=1`` (``_ARCHIVE_ACTIVE_SQL``) while rewind, undo and replace
    mark ``active=0, compacted=0``; a rotating compaction leaves the turn on a compression ancestor of
    *physical*, still displayed (``active=1 OR compacted=1``)."""
    row = conn.execute('SELECT session_id, role, active, compacted FROM messages WHERE id=?',
                       (message_id,)).fetchone()
    if row is None or row['role'] != 'user':
        return False
    if row['session_id'] == physical:
        return row['active'] == 0 and row['compacted'] == 1
    if not (row['active'] == 1 or row['compacted'] == 1):
        return False
    from hermes_state_sessions import _expand_compression_lineage_ids
    from hermes_state_compression import _CHAIN_CAP
    lineage, frontier = {physical}, [physical]
    for _ in range(_CHAIN_CAP):
        frontier = [sid for sid in _expand_compression_lineage_ids(conn, frontier) if sid not in lineage]
        if not frontier:
            break
        lineage.update(frontier)
    return row['session_id'] in lineage


def _carrier_live_view(db, conn, session_id, message_id):
    from agent.context_compressor import split_user_originated_turn
    row = conn.execute('SELECT * FROM messages WHERE id=? AND session_id=? AND active=1',
                       (message_id, session_id)).fetchone()
    message = row and db._row_to_message_dict(row, warn_context='rewind target', summary_flag=True)
    handoff, live = split_user_originated_turn(message) if message else (None, None)
    return live if handoff is not None else None


def _import(db, conn, session_id, payload):
    rows = payload['sessions']
    if len(rows) > db._IMPORT_MAX_SESSIONS:
        raise RuntimeStoreError('invalid_params')
    normalized, errors = db._validate_import_payload(rows)
    if errors or not normalized or session_id != normalized[0]['session']['id']:
        raise RuntimeStoreError('invalid_params')
    imported, skipped, parents = [], [], []
    for item in normalized:
        raw = item['session']
        sid = raw['id']
        from hermes_db.domains.runtime.receipts import RETIRED_PREFIX
        if conn.execute('SELECT 1 FROM state_meta WHERE key=?', (RETIRED_PREFIX + sid,)).fetchone():
            # Refused by name at import time: a row restored beside the fence would refuse every turn.
            raise RuntimeStoreError('admission_conflict', field='sessions',
                                    detail=f'session {sid} was deleted here; a deleted session is not restored')
        if conn.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
            skipped.append(sid)
            continue
        db._import_session_row(conn, raw, item['messages'], sid)
        if raw.get('parent_session_id'):
            parents.append((sid, raw['parent_session_id']))
        imported.append(sid)
    # A parent outside this payload is kept only when it is history this importer already
    # controls: its import binding names the child's owner (written by import_history_control in this
    # transaction). Linking under any other row would graft the import onto a foreign chain,
    # which a later chain-aware delete of the import would then remove.
    from hermes_state_mutation_binding import bindings_agree, history_binding
    # Rows imported now, not payload ids: a payload naming an existing foreign id skips that row.
    fresh = set(imported)
    foreign = [(sid, parent) for sid, parent in parents if parent not in fresh and (
        history_binding(conn, parent) is None or not bindings_agree(history_binding(conn, parent), history_binding(conn, sid)))]
    parents = [link for link in parents if link not in foreign]
    detached = db._attach_import_parents(conn, parents) + len(foreign)
    return set(imported), {'ok': True, 'imported': len(imported), 'skipped': len(skipped),
        'imported_ids': imported, 'skipped_ids': skipped, 'detached': detached, 'errors': []}
