"""Connection/scope session lineage reads shared by Session components and owner Worker receipts."""
from hermes_db.domains.sessions.postgres.operations import compression_state as state
from hermes_db.domains.sessions.postgres.queries import messages as message_lookup_repo, sessions as session_rows
from hermes_db.tables.conversations import messages, sessions as session_table
from sqlalchemy import select
from hermes_db.tables.gateway import conversation_generations
from hermes_db.core.values import explicit_fork, model_config

def get_compression_chain(conn, scope, session_id):
    from hermes_db.domains.sessions.postgres.queries import sessions
    from hermes_db.core.values import preferred_children
    children = preferred_children(sessions.lineage_rows(conn, scope, session_id))
    chain = [session_id] if session_id else []
    while chain and chain[-1] in children:
        child = children[chain[-1]]
        if child in chain:
            raise RuntimeError('Compression lineage contains a cycle')
        chain.append(child)
    return chain

def get_compression_tip(conn, scope, session_id):
    chain = get_compression_chain(conn, scope, session_id)
    return chain[-1] if chain else session_id

def get_compression_lineage(conn, scope, session_id):
    return state.lineage(conn, scope, session_id)

def get_conversation_root(conn, scope, session_id):
    current, seen = (session_id, set())
    while current not in seen:
        seen.add(current)
        row = session_rows.raw_session(conn, scope, current)
        if not row or not row['parent_session_id']:
            return current
        parent = session_rows.raw_session(conn, scope, row['parent_session_id'])
        if not parent:
            return current
        current = parent['id']
    raise ValueError('Conversation lineage contains a cycle')

def resolve_resume_session_id(conn, scope, session_id):
    if not session_id:
        return session_id
    initial = session_rows.compression_tip(conn, scope, session_id) or session_id
    current, best, seen = (initial, None, set())
    for _ in range(32):
        if current in seen:
            break
        seen.add(current)
        if conn.scalar(select(messages.c.id).where(message_lookup_repo.where(scope, [current])).limit(1)) is not None:
            best = current
        children = conn.execute(select(session_table).where(session_table.c.store_id == scope.require_store_id(), session_table.c.parent_session_id == current).order_by(session_table.c.started_at.desc(), session_table.c.id.desc())).mappings()
        child = next((row for row in children if row['source'] != 'tool' and (not explicit_fork(row))), None)
        if child is None:
            break
        current = child['id']
    return best or initial

def latest_conversation_boundary(conn, scope, session_key, source):
    if not session_key or not source:
        return None
    table = conversation_generations
    generation = conn.scalar(select(table.c.generation).where(table.c.store_id == scope.require_store_id(), table.c.session_key == session_key, table.c.source == source))
    return generation if generation and generation > 0 else None

def declared_scope_identity(conn, scope, session_id):
    row = session_rows.get_session(conn, scope, session_id)
    if row is None:
        return (False, '')
    config = model_config(row['model_config'])
    markers = [config.get(name) for name in ('_branched_from', '_delegate_from')]
    parent = row['parent_session_id']
    fork = row['source'] == 'tool' or (parent in markers if parent else any(value is not None for value in markers))
    return (fork, str(row['source'] or '').strip())

def get_tool_rotation_root(conn, scope, session_id):
    row, seen = (session_rows.raw_session(conn, scope, session_id), {session_id})
    while row and row['source'] == 'tool':
        parent_id = row['parent_session_id']
        if not parent_id or parent_id in seen or is_explicit_fork_child_row({**row, 'source': None}, include_reset=True):
            break
        parent = session_rows.raw_session(conn, scope, parent_id)
        if not parent or parent['source'] != 'tool' or parent['end_reason'] != 'compression':
            break
        seen.add(parent_id)
        row = parent
    return row['id'] if row else session_id

def is_explicit_fork_child_row(row, *, include_reset=False):
    if row.get('source') == 'tool':
        return True
    cfg = model_config(row.get('model_config'))
    names = ('_branched_from', '_delegate_from', '_reset_from') if include_reset else ('_branched_from', '_delegate_from')
    markers = [cfg.get(name) for name in names]
    parent = row.get('parent_session_id')
    return parent in markers if parent else any(marker is not None for marker in markers)
