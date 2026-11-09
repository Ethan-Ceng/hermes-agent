"""Kanban notify workflow; original connection, fence and off-connection effect boundaries are preserved."""
import time
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.kanban.postgres import repository as repo
from hermes_db.tables.kanban import events, tasks
from hermes_db.tables.kanban_notify import subscriptions as subs, TEXT_FIELDS
from hermes_db.core.values import encode_text

def _key(store, task_id, platform, chat_id, thread_id=None):
    values = dict(task_id=task_id, platform=platform, chat_id=chat_id, thread_id=thread_id or '')
    return and_(repo.scope(subs, store), *(subs.c[name] == encode_text(value) for name, value in values.items()))

def _platform_key(value):
    return value.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))

def _decode(row):
    from hermes_db.domains.kanban.rules import _decode_notify_delivery_metadata
    item = repo.decode_record(row)
    item.pop('store_id', None)
    item.pop('board_id', None)
    item.pop('platform_key', None)
    item['delivery_metadata'] = _decode_notify_delivery_metadata(item['delivery_metadata'])
    return item

def _max_event(conn, store, task_id):
    return conn.scalar(select(func.coalesce(func.max(events.c.id), 0)).where(repo.key(store, task_id, events)))

def _add(conn, store, fields):
    from hermes_db.domains.kanban.rules import _NOTIFY_DELIVERY_MODES, _decode_notify_delivery_metadata, _encode_notify_delivery_metadata
    fields = dict(fields, thread_id=fields.get('thread_id') or '')
    condition = _key(store, **{key: fields[key] for key in ('task_id', 'platform', 'chat_id', 'thread_id')})
    existing = conn.execute(select(subs).where(condition)).mappings().one_or_none()
    metadata = _decode_notify_delivery_metadata(repo.decode_record(existing)['delivery_metadata']) if existing else {}
    metadata.update(fields.get('delivery_metadata') or {})
    metadata_json = _encode_notify_delivery_metadata(metadata)
    valid_mode = fields.get('delivery_mode') if fields.get('delivery_mode') in _NOTIFY_DELIVERY_MODES else None
    if existing is None:
        values = {name: fields.get(name) for name in TEXT_FIELDS}
        values.update(chat_type=fields.get('chat_type') or 'dm', delivery_metadata=metadata_json, delivery_mode=valid_mode or ('notify+wake' if fields['platform'] == 'api_server' else 'notify'))
        conn.execute(subs.insert().values(**repo.owner(store), **{key: encode_text(value) for key, value in values.items()}, platform_key=encode_text(_platform_key(fields['platform'])), created_at=int(time.time()), last_event_id=_max_event(conn, store, fields['task_id'])))
        return
    values = {name: encode_text(fields[name]) for name in ('chat_type', 'user_id', 'user_id_alt', 'notifier_profile') if fields.get(name) and (name == 'chat_type' or not existing[name])}
    if valid_mode:
        values['delivery_mode'] = encode_text(valid_mode)
    if metadata_json:
        values['delivery_metadata'] = encode_text(metadata_json)
    if values:
        conn.execute(update(subs).where(condition).values(**values))

def add_notify_sub(store, **fields):
    with store.write() as conn:
        _add(conn, store, fields)
        store.command_result(conn, None)

def _owners(profiles, include_unowned):
    if profiles is None:
        return True
    names = sorted({str(value).strip() for value in profiles if str(value).strip()})
    return or_(subs.c.notifier_profile.in_([encode_text(name) for name in names]), and_(include_unowned, or_(subs.c.notifier_profile.is_(None), subs.c.notifier_profile == b'')))

def list_notify_subs(store, task_id=None, *, notifier_profiles=None, include_unowned=False):
    condition = repo.scope(subs, store) & _owners(notifier_profiles, include_unowned)
    if task_id is not None:
        condition &= subs.c.task_id == encode_text(task_id)
    with store.read() as conn:
        return [_decode(row) for row in conn.execute(select(subs).where(condition)).mappings()]


def remove_notify_sub(store, **key):
    with store.write() as conn:
        return store.command_result(conn, conn.execute(delete(subs).where(_key(store, **key))).rowcount > 0)

def retarget_notify_subs(store, *, platform, from_chat_ids, to_chat_id):
    ids = sorted({value for value in from_chat_ids if value and value != to_chat_id})
    if not ids:
        return 0
    moved = 0
    with store.write() as conn:
        repo.lock_board(conn, store)
        rows = conn.execute(select(subs).where(repo.scope(subs, store), subs.c.platform_key == encode_text(_platform_key(platform)), subs.c.chat_id.in_([encode_text(value) for value in ids])).order_by(subs.c.task_id, subs.c.platform, subs.c.chat_id, subs.c.thread_id).with_for_update()).mappings().all()
        for row in rows:
            values = {column.name: row[column.name] for column in subs.c}
            values['chat_id'] = encode_text(to_chat_id)
            moved += int(conn.execute(insert(subs).values(**values).on_conflict_do_nothing()).rowcount > 0)
            old = {key: repo.decode_record(row)[key] for key in ('task_id', 'platform', 'chat_id', 'thread_id')}
            conn.execute(delete(subs).where(_key(store, **old)))
        return store.command_result(conn, moved)

def purge_stale_done_notify_subs(store, *, max_age_days=30):
    try:
        days = int(max_age_days)
    except (TypeError, ValueError):
        days = 30
    if days <= 0:
        return 0
    activity = select(func.max(events.c.created_at)).where(events.c.store_id == tasks.c.store_id, events.c.board_id == tasks.c.board_id, events.c.task_id == tasks.c.id).correlate(tasks).scalar_subquery()
    old = select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.status.in_([b'done', b'blocked']), func.coalesce(activity, tasks.c.completed_at, tasks.c.created_at, 0) < int(time.time()) - days * 86400)
    with store.write() as conn:
        return conn.execute(delete(subs).where(repo.scope(subs, store), subs.c.task_id.in_(old))).rowcount

def _unseen(conn, store, key, kinds):

    cursor = conn.scalar(select(subs.c.last_event_id).where(_key(store, **key)))
    if cursor is None:
        return (0, [])
    query = select(events).where(repo.key(store, key['task_id'], events), events.c.id > cursor)
    kind_list = list(kinds) if kinds else None
    if kind_list:
        query = query.where(events.c.kind.in_([encode_text(kind) for kind in kind_list]))
    rows = [store.result_values.event(repo.decode_record(row)) for row in conn.execute(query.order_by(events.c.id)).mappings()]
    return (rows[-1].id if rows else cursor, rows)

def unseen_events_for_sub(store, *, kinds=None, **key):
    with store.read() as conn:
        return _unseen(conn, store, key, kinds)

def claim_unseen_events_for_sub(store, *, kinds=None, **key):
    with store.write() as conn:
        old = conn.scalar(select(subs.c.last_event_id).where(_key(store, **key)))
        if old is None:
            return (0, 0, [])
        new, rows = _unseen(conn, store, key, kinds)
        conn.execute(update(subs).where(_key(store, **key), subs.c.last_event_id == old).values(last_event_id=new))
        return (old, new, rows)

def advance_notify_cursor(store, *, new_cursor, **key):
    with store.write() as conn:
        conn.execute(update(subs).where(_key(store, **key)).values(last_event_id=int(new_cursor)))

def record_notify_ping(store, *, event_id, **key):
    with store.write() as conn:
        conn.execute(update(subs).where(_key(store, **key)).values(last_ping_event_id=func.greatest(subs.c.last_ping_event_id, int(event_id))))

def rewind_notify_cursor(store, *, claimed_cursor, old_cursor, **key):
    with store.write() as conn:
        return conn.execute(update(subs).where(_key(store, **key), subs.c.last_event_id == int(claimed_cursor)).values(last_event_id=int(old_cursor))).rowcount > 0

def inherit(conn, store, child_id, parents, *, created_at=None):
    parent_ids = list(dict.fromkeys(encode_text(value) for value in parents if value))
    if not parent_ids:
        return
    cursor = _max_event(conn, store, child_id)
    rows = conn.execute(select(subs).where(repo.scope(subs, store), subs.c.task_id.in_(parent_ids)).order_by(subs.c.task_id, subs.c.platform, subs.c.chat_id, subs.c.thread_id)).mappings().all()
    for row in rows:
        values = {name: row[name] for name in TEXT_FIELDS}
        values.update(task_id=encode_text(child_id), chat_type=row['chat_type'] or b'dm', delivery_mode=row['delivery_mode'] or b'notify')
        conn.execute(insert(subs).values(**repo.owner(store), **values, platform_key=row['platform_key'], created_at=int(time.time()) if created_at is None else created_at, last_event_id=cursor).on_conflict_do_nothing())

def count_subscriptions(conn, scope, board_id, *, notifier_profiles=None, include_unowned=False, platform=None, chat_id=None, thread_id=None):
    condition = and_(subs.c.store_id == scope.require_store_id(), subs.c.board_id == board_id, _owners(notifier_profiles, include_unowned))
    for name, value in (('platform_key', _platform_key(platform) if platform is not None else None), ('chat_id', chat_id), ('thread_id', thread_id)):
        if value is not None:
            condition &= subs.c[name] == encode_text(value)
    return conn.scalar(select(func.count()).select_from(subs).where(condition))
