"""Explicit merge-era data repair, never invoked by ordinary store opens.

Called only by revision 0031 under schema table-write fences. Keep the migration
contract and idempotence tests when changing the shared transcript projections.
"""

import json
import time
from pathlib import Path
from sqlalchemy import func, select, text

from hermes_db.errors import StorageSchemaError
from hermes_db.message_codec import codec
from hermes_db.repositories import messages as message_repo, sessions as repo
from hermes_db.scope import DatabaseScope
from hermes_db.tables.conversations import messages, sessions
from hermes_db.tables.gateway import compression_locks, session_turn_leases
from hermes_db.tables.metadata import SCHEMA
from hermes_db.tables.runtime import worker_executions
from hermes_db.core.values import encode_config, explicit_fork, model_config


def repair(conn, schema):
    quote = conn.dialect.identifier_preparer.quote
    # Block legacy writers before checking ownership. No network/daemon calls occur here.
    names = ('sessions', 'messages', 'session_turn_leases', 'compression_locks', 'worker_executions')
    conn.execute(text('LOCK TABLE ' + ','.join(quote(schema) + '.' + quote(name) for name in names)
                      + ' IN SHARE ROW EXCLUSIVE MODE'))
    conn = conn.execution_options(schema_translate_map={SCHEMA: schema})
    cursor = ('', '')
    from sqlalchemy import tuple_
    while rows := conn.execute(select(sessions).where(tuple_(sessions.c.store_id, sessions.c.id) > cursor)
                               .order_by(sessions.c.store_id, sessions.c.id).limit(128)).mappings().all():
        for saved in rows:
            scope = DatabaseScope(Path('.'), saved['store_id'])
            row = repo.raw_session(conn, scope, saved['id'])
            _repair_delegate(conn, scope, row)
            _repair_refusal(conn, scope, repo.raw_session(conn, scope, row['id']))
        cursor = rows[-1]['store_id'], rows[-1]['id']


def _unowned(conn, scope, ids, roots):
    now = time.time()
    probes = ((session_turn_leases, session_turn_leases.c.conversation_id, roots),
              (compression_locks, compression_locks.c.session_id, ids))
    for table, column, values in probes:
        if conn.scalar(select(column).where(table.c.store_id == scope.require_store_id(), column.in_(values),
                                             table.c.expires_at > now).limit(1)) is not None:
            raise StorageSchemaError('Merge data repair requires stopped and drained session/compression owners; retry explicit db upgrade')
    if conn.scalar(select(worker_executions.c.execution_id).where(worker_executions.c.store_id == scope.require_store_id(),
        worker_executions.c.session_id.in_(ids), worker_executions.c.status != 'terminal').limit(1)) is not None:
        raise StorageSchemaError('Merge data repair requires settled Worker ownership; retry explicit db upgrade')


def _repair_delegate(conn, scope, row):
    cfg, parent_id = model_config(row['model_config']), row['parent_session_id']
    if row['source'] != 'subagent' or not parent_id or cfg.get('_delegate_from') is not None:
        return
    parent = repo.raw_session(conn, scope, parent_id)
    if parent and parent['source'] == 'subagent' and parent['end_reason'] == 'compression':
        return
    old_root = row['lineage_root_id']
    group = list(conn.execute(select(sessions).where(sessions.c.store_id == scope.require_store_id(),
                                                    sessions.c.lineage_root_id == old_root)).mappings())
    by_id = {entry['id']: entry for entry in group}
    descendants, frontier = {row['id']}, [row['id']]
    while frontier:
        fresh = {entry['id'] for entry in group if entry['parent_session_id'] in frontier
                 and by_id[entry['parent_session_id']]['end_reason'] == 'compression' and not explicit_fork(entry)} - descendants
        descendants.update(fresh)
        frontier = list(fresh)
    _unowned(conn, scope, descendants, {old_root, row['id']})
    repo.create_root(conn, scope, row['id'])
    repo.update_session(conn, scope, row['id'], {'model_config': encode_config({**cfg, '_delegate_from': parent_id})})
    conn.execute(sessions.update().where(sessions.c.store_id == scope.require_store_id(), sessions.c.id.in_(descendants))
                 .values(lineage_root_id=row['id']))


def _chat(conn, scope, row):
    cfg = model_config(row['model_config'])
    if row['source'] in ('subagent', 'cron', 'batch', 'kanban', 'curator', 'tool') or cfg.get('_delegate_from') is not None:
        return False
    parent = repo.raw_session(conn, scope, row['parent_session_id']) if row['parent_session_id'] else None
    if parent:
        from hermes_state_common import _RESET_END_REASONS
        branch = cfg.get('_branched_from') is not None or (parent['end_reason'] == 'branched'
            and parent['ended_at'] is not None and row['started_at'] >= parent['ended_at'])
        reset = cfg.get('_reset_from') is not None or parent['end_reason'] in _RESET_END_REASONS
        if not branch and not reset and parent['end_reason'] != 'compression':
            return False
    return True


def _holds_refusal(conn, scope, row):
    from hermes_state_legacy_refusal import _is_refusal_boundary
    current, seen = row, set()
    while current and current['id'] not in seen:
        ancestor = current['id'] != row['id']
        conditions = [] if ancestor else [messages.c.active == 0]
        rows = message_repo.select_rows(conn, scope, [current['id']], messages.c.display_kind == 'failed_turn', *conditions)
        if any(_is_refusal_boundary(codec, candidate) for candidate in rows):
            return True
        seen.add(current['id'])
        if explicit_fork(current):
            break
        parent = repo.raw_session(conn, scope, current['parent_session_id']) if current['parent_session_id'] else None
        current = parent if parent and parent['end_reason'] == 'compression' else None
    return False


def _repair_refusal(conn, scope, row):
    from hermes_state_legacy_refusal import _is_refusal_boundary, _locked_tail
    from agent.turn_failure_copy import CONTENT_REFUSED_DISPLAY_KIND, CONTENT_REFUSED_METADATA_KEY, CONTENT_REFUSED_NOTICE
    if row['end_reason'] == 'compression' or not _chat(conn, scope, row):
        return
    # One indexed newest-boundary probe avoids loading ordinary transcript bodies.
    settled = select(messages).where(message_repo.where(scope, [row['id']]), messages.c.active == 1,
        messages.c.role == 'assistant', (messages.c.display_kind == 'failed_turn') | (
            (func.coalesce(messages.c.display_kind, '') == '') & func.coalesce(messages.c.tool_calls, '').in_(['', '[]'])))
    newest = conn.execute(settled.order_by(messages.c.id.desc()).limit(1)).mappings().one_or_none()
    if newest is None or not _is_refusal_boundary(codec, newest) or _holds_refusal(conn, scope, row):
        return
    rows = message_repo.select_rows(conn, scope, [row['id']], messages.c.active == 1,
                                    messages.c.role.not_in(['session_meta', 'system']))
    plan = _locked_tail(codec, rows)
    if not plan:
        return
    _unowned(conn, scope, [row['id']], [row['lineage_root_id']])
    for shown, ids in plan:
        conn.execute(messages.update().where(message_repo.where(scope, [row['id']]), messages.c.id.in_(ids)).values(active=0))
        if shown is not None:
            target = message_repo.one(conn, scope, row['id'], shown)
            metadata = codec._decode_display_metadata(target['display_metadata']) or {}
            metadata[CONTENT_REFUSED_METADATA_KEY] = {'notice': CONTENT_REFUSED_NOTICE}
            message_repo.update_row(conn, scope, row['id'], shown, {'compacted': 1,
                'display_kind': CONTENT_REFUSED_DISPLAY_KIND, 'display_metadata': codec._encode_display_metadata(metadata)})
    live = message_repo.select_rows(conn, scope, [row['id']], messages.c.active == 1)
    from hermes_state_messages import _tool_calls_len
    repo.update_session(conn, scope, row['id'], {'message_count': len(live),
        'tool_call_count': sum(_tool_calls_len(entry['tool_calls'], scalar=1) for entry in live),
        'rewind_count': func.coalesce(sessions.c.rewind_count, 0) + 1})
    message_repo.reconcile_orders(conn, scope, row['id'])
    message_repo.bump_revision(conn, scope, row['id'])
