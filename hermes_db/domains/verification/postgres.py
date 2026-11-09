"""Evidence operations and scoped retention queries sharing the caller-owned short transaction."""
import json
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.tables.verification import verification_events as events, verification_locks as locks, verification_state as states
from hermes_db.core.values import decode_text, encode_text
EXACT_FIELDS = ('session_id', 'cwd', 'root', 'command', 'canonical_command', 'output_summary')

def _lock_store(conn, scope):
    store_id = scope.require_store_id()
    conn.execute(insert(locks).values(store_id=store_id).on_conflict_do_nothing())
    conn.execute(select(locks.c.store_id).where(locks.c.store_id == store_id).with_for_update()).one()

def _state_key(scope, session_id, root):
    return and_(states.c.store_id == scope.require_store_id(), states.c.session_id == encode_text(session_id), states.c.root == encode_text(root))

def _state(conn, scope, session_id, root):
    return conn.execute(select(states).where(_state_key(scope, session_id, root))).mappings().one_or_none()

def _save_event(conn, scope, evidence, created_at):
    values = dict(evidence)
    values.update({key: encode_text(values[key]) for key in EXACT_FIELDS})
    return conn.scalar(events.insert().values(store_id=scope.require_store_id(), created_at=created_at, **values).returning(events.c.id))

def _point_to_event(conn, scope, session_id, root, event_id, *, share):
    statement = insert(states).values(store_id=scope.require_store_id(), session_id=encode_text(session_id), root=encode_text(root), last_event_id=event_id, last_edit_at=None, changed_paths_json='[]')
    values = {'last_event_id': event_id, 'last_edit_at': None, 'changed_paths_json': '[]'}
    conn.execute(statement.on_conflict_do_update(index_elements=list(states.primary_key.columns), set_=values))
    if share:
        conn.execute(update(states).where(states.c.store_id == scope.require_store_id(), states.c.root == encode_text(root), states.c.session_id != encode_text(session_id)).values(**values))

def _mark_edited(conn, scope, session_id, root, changed, edited_at):
    row = _state(conn, scope, session_id, root)
    existing = json.loads(row['changed_paths_json']) if row else []
    paths = json.dumps(sorted(set(existing) | set(changed))[-200:])
    statement = insert(states).values(store_id=scope.require_store_id(), session_id=encode_text(session_id), root=encode_text(root), last_edit_at=edited_at, changed_paths_json=paths)
    conn.execute(statement.on_conflict_do_update(index_elements=list(states.primary_key.columns), set_={'last_edit_at': edited_at, 'changed_paths_json': paths}))

def _event(conn, scope, event_id):
    row = conn.execute(select(events).where(events.c.store_id == scope.require_store_id(), events.c.id == event_id)).mappings().one_or_none()
    return _decode_event(row)

def _decode_event(row):
    if row is None:
        return None
    result = dict(row)
    result.pop('store_id')
    result.update({key: decode_text(result[key]) for key in EXACT_FIELDS})
    return result

def _shared_event(conn, scope, root, since):
    query = select(events).where(events.c.store_id == scope.require_store_id(), events.c.root == encode_text(root), events.c.kind == 'verify', events.c.status == 'passed', events.c.scope == 'full')
    if since:
        query = query.where(events.c.created_at >= since)
    return _decode_event(conn.execute(query.order_by(events.c.id.desc()).limit(1)).mappings().one_or_none())

def _prune(conn, scope, session_id, root, *, cutoff, per_root_limit, total_limit):
    store_id = scope.require_store_id()
    referenced = select(states.c.last_event_id).where(states.c.store_id == store_id, states.c.last_event_id.is_not(None))
    unreferenced = events.c.id.not_in(referenced)
    key = and_(events.c.store_id == store_id, events.c.session_id == encode_text(session_id), events.c.root == encode_text(root))
    retained = select(events.c.id).where(key).order_by(events.c.id.desc()).limit(per_root_limit)
    conn.execute(delete(events).where(key, events.c.id.not_in(retained), unreferenced))
    old_ids = select(events.c.id).where(events.c.store_id == store_id, events.c.created_at < cutoff)
    conn.execute(delete(states).where(states.c.store_id == store_id, or_(states.c.last_edit_at < cutoff, and_(states.c.last_edit_at.is_(None), states.c.last_event_id.in_(old_ids)))))
    conn.execute(delete(events).where(events.c.store_id == store_id, events.c.created_at < cutoff, unreferenced))
    retained = select(events.c.id).where(events.c.store_id == store_id).order_by(events.c.id.desc()).limit(total_limit)
    conn.execute(delete(events).where(events.c.store_id == store_id, events.c.id.not_in(retained), unreferenced))

def record(resource, evidence, created_at, *, cutoff, per_root_limit, total_limit):
    """Clock and retention policy belong to the owner, never the compute producer."""
    with resource.write() as conn:
        _lock_store(conn, resource.scope)
        event_id = _save_event(conn, resource.scope, evidence, created_at)
        share = evidence['kind'] == 'verify' and evidence['status'] == 'passed' and (evidence['scope'] == 'full')
        _point_to_event(conn, resource.scope, evidence['session_id'], evidence['root'], event_id, share=share)
        _prune(conn, resource.scope, evidence['session_id'], evidence['root'], cutoff=cutoff, per_root_limit=per_root_limit, total_limit=total_limit)
    return {'id': event_id, **evidence, 'created_at': created_at}

def mark_edited(resource, session_id, root, changed, edited_at):
    with resource.write() as conn:
        _lock_store(conn, resource.scope)
        _mark_edited(conn, resource.scope, session_id, root, changed, edited_at)
    return {'session_id': session_id, 'root': root, 'last_edit_at': edited_at, 'changed_paths': changed}

def status(resource, session_id, root):
    with resource.read() as conn:
        state = _state(conn, resource.scope, session_id, root)
        result = {'evidence': None, 'root': root, 'session_id': session_id, 'changed_paths': []}
        if state is None:
            return {'status': 'unverified', **result}
        result['changed_paths'] = json.loads(state['changed_paths_json'])
        event = _event(conn, resource.scope, state['last_event_id']) if state['last_event_id'] is not None else None
        edited_at = state['last_edit_at']
        stale = bool(event is not None and edited_at and (edited_at > event['created_at']))
        if event is None or stale:
            shared = _shared_event(conn, resource.scope, root, edited_at)
            if shared is not None:
                event, stale = (shared, False)
        if event is None:
            return {'status': 'unverified', **result}
        return {'status': 'stale' if stale else event['status'], **result, 'evidence': event}
