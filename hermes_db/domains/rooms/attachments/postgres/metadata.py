"""Room attachment_metadata workflow; original connection, fence and off-connection effect boundaries are preserved."""
from hermes_db.domains.rooms.attachments import rules as _storage_shared_1
from sqlalchemy import func, select, update, delete
from hermes_db.domains.rooms.postgres import repository as room_repo, repository as repo
from hermes_db.tables.room_attachments import attachments, blobs, cleanup, roots
import json
from hermes_db.domains.rooms.rules import EventAttachmentConflictError
from hermes_db.tables.rooms import rooms, retired, events
from collections import Counter
from sqlalchemy.dialects.postgresql import insert
import secrets

def validate_retry(row, fields):
    if any(row[key] != fields[key] for key in ('kind', 'name', 'mime', 'size', 'sha256')):
        raise _storage_shared_1.AttachmentConflictError('upload_id was already used for different attachment content')

def _quota(conn, store, fields, limits):
    count, size = totals(conn, store, room_id=fields['room_id'], live_only=True)
    if size + fields['size'] > limits['room_quota_bytes']:
        raise _storage_shared_1.AttachmentQuotaError('room attachment quota exceeded')
    if count >= limits['room_quota_count']:
        raise _storage_shared_1.AttachmentQuotaError('room attachment count quota exceeded')
    total_count, _ = totals(conn, store)
    if total_count >= limits['gateway_quota_count']:
        raise _storage_shared_1.AttachmentQuotaError('gateway attachment count quota exceeded')
    count, size = totals(conn, store, room_id=fields['room_id'], state='uploaded')
    if size + fields['size'] > _storage_shared_1.MAX_ROOM_UNCOMMITTED_BYTES or count + 1 > _storage_shared_1.MAX_ROOM_UNCOMMITTED_COUNT:
        raise _storage_shared_1.AttachmentQuotaError('room uncommitted upload quota exceeded')

def put(store, *, fields, candidate_blob, now, limits):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        previous = attachment(conn, store, room_id=fields['room_id'], upload_id=fields['upload_id'])
        if previous is not None:
            validate_retry(previous, fields)
            return (previous, True)
        _quota(conn, store, fields, limits)
        blob = _blob_row(conn, store, sha256=fields['sha256'])
        if blob is None:
            physical = conn.scalar(select(func.coalesce(func.sum(blobs.c.size), 0)).where(room_repo.scope(blobs, store)))
            if physical + fields['size'] > limits['gateway_quota_bytes']:
                raise _storage_shared_1.AttachmentQuotaError('gateway attachment quota exceeded')
            blob_id = candidate_blob
            room_repo.insert_row(conn, store, blobs, dict(blob_id=blob_id, sha256=fields['sha256'], size=fields['size'], ref_count=1, created_at=now))
        else:
            blob_id = blob['blob_id']
            conn.execute(update(blobs).where(room_repo.key(blobs, store, dict(blob_id=blob_id))).values(ref_count=blobs.c.ref_count + 1))
        room_repo.insert_row(conn, store, attachments, dict(fields, blob_id=blob_id, event_id=None, recipient_member_ids_json='[]', viewer_access=0, state='uploaded', created_at=now, updated_at=now, expires_at=now + _storage_shared_1.UNCOMMITTED_TTL_SECONDS))
        return (attachment(conn, store, fields['attachment_id']), False)

def find_upload(store, *, room_id, upload_id, now):
    with store.read() as conn:
        row = attachment(conn, store, room_id=room_id, upload_id=upload_id)
        if row is None or row['state'] == 'disbanded' or (row['expires_at'] is not None and row['expires_at'] <= now):
            return None
        return row

def validate_row(row, entry, *, room_id, event_id, recipients_json, viewer_access, now):
    if row is None or row['room_id'] != room_id:
        raise _storage_shared_1.AttachmentNotFoundError('attachment is not uploaded for this room')
    if {key: row[key] for key in _storage_shared_1._ATTACHMENT_FIELDS} != entry:
        raise _storage_shared_1.AttachmentConflictError('attachment manifest metadata does not match the uploaded bytes')
    if row['expires_at'] is not None and row['expires_at'] <= now:
        raise _storage_shared_1.AttachmentNotFoundError('attachment has expired')
    if row['state'] == 'disbanded':
        raise _storage_shared_1.AttachmentNotFoundError('attachment belongs to a disbanded room')
    if row['state'] == 'committed' and ((row['event_id'] or '') != event_id or row['recipient_member_ids_json'] != recipients_json or bool(row['viewer_access']) != bool(viewer_access)):
        raise _storage_shared_1.AttachmentConflictError('attachment is already owned by a different room event')

def prepare(store, *, manifest, **scope):
    with store.read() as conn:
        rows = [attachment(conn, store, entry['attachment_id']) for entry in manifest]
        for row, entry in zip(rows, manifest):
            validate_row(row, entry, **scope)
        return rows

def commit(store, *, manifest, expires_at, **scope):
    transitioned = []
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        rows = [attachment(conn, store, entry['attachment_id']) for entry in manifest]
        for row, entry in zip(rows, manifest):
            validate_row(row, entry, **scope)
        for row in rows:
            if row['state'] == 'uploaded':
                transitioned.append(row['attachment_id'])
                conn.execute(update(attachments).where(room_repo.key(attachments, store, dict(attachment_id=row['attachment_id'])), attachments.c.state == 'uploaded').values(event_id=scope['event_id'], recipient_member_ids_json=scope['recipients_json'].encode(), viewer_access=int(bool(scope['viewer_access'])), state='committed', updated_at=scope['now'], expires_at=expires_at))
    return (manifest, tuple(transitioned))

def abort(store, *, room_id, event_id, attachment_ids, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        event = owner_event(conn, store, room_id, event_id)
        published = {item.get('attachment_id') for item in json.loads(event['payload_json']).get('attachments', []) if isinstance(item, dict)} if event is not None else set()
        selected = [value for value in attachment_ids if value not in published]
        if not selected:
            return 0
        return conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.event_id == event_id, attachments.c.state == 'committed', attachments.c.attachment_id.in_(selected)).values(event_id=None, recipient_member_ids_json=b'[]', viewer_access=0, state='uploaded', updated_at=now, expires_at=now + _storage_shared_1.UNCOMMITTED_TTL_SECONDS)).rowcount

def retain_event(store, *, room_id, event_id, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        if room_repo.event(conn, store, room_id, event_id) is None:
            raise _storage_shared_1.AttachmentConflictError('attachment owner event is not durable in the room log')
        return conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.event_id == event_id, attachments.c.state == 'committed').values(expires_at=None, updated_at=now)).rowcount

def retain_message_attachments(conn, store, *, room_id, event_id, manifest, now):
    normalized = _storage_shared_1.validate_manifest(manifest)
    if normalized != manifest:
        raise _storage_shared_1.AttachmentError('published attachment metadata must be canonical')
    for entry in normalized:
        row = attachment(conn, store, entry['attachment_id'])
        if row is None or row['room_id'] != room_id or row['event_id'] != event_id or (row['state'] != 'committed') or (row['viewer_access'] != 1) or (row['expires_at'] is not None and row['expires_at'] <= now) or any((row[key] != value for key, value in entry.items())):
            raise EventAttachmentConflictError('attachment commitment changed before event publication')
    if normalized:
        conn.execute(update(attachments).where(room_repo.scope(attachments, store), attachments.c.attachment_id.in_([entry['attachment_id'] for entry in normalized])).values(expires_at=None, updated_at=now))

def viewer_room(conn, store, *, room_id, authority_gateway_id, authority_epoch):
    row = conn.execute(select(rooms).where(room_repo.scope(rooms, store, room_id))).mappings().one_or_none()
    if row is None or row['disbanded_at'] is not None or row['authority_gateway_id'] != authority_gateway_id or (row['authority_epoch'] != authority_epoch):
        raise _storage_shared_1.AttachmentNotFoundError('Group Chat viewer authority changed')

def owner_event(conn, store, room_id, event_id):
    event = room_repo.event(conn, store, room_id, event_id)
    return event if event is not None and event['kind'] in {'message.user', 'message.member'} else None

def committed_row(conn, store, *, room_id, attachment_id, recipient_member_id, normalized_event, viewer, now):
    row = attachment(conn, store, attachment_id, room_id=room_id)
    if row is None or row['state'] != 'committed':
        raise _storage_shared_1.AttachmentNotFoundError('attachment is not committed for this room')
    if row['expires_at'] is not None and row['expires_at'] <= now:
        raise _storage_shared_1.AttachmentNotFoundError('attachment has expired')
    if normalized_event is not None and (row['event_id'] or '') != normalized_event:
        raise _storage_shared_1.AttachmentNotFoundError('attachment is not owned by this room event')
    if row['viewer_access']:
        event = owner_event(conn, store, room_id, row['event_id'] or '')
        payload = json.loads(event['payload_json']) if event is not None else None
        manifest = {key: row[key] for key in ('attachment_id', 'kind', 'name', 'size', 'mime')}
        published = payload.get('attachments') if isinstance(payload, dict) else None
        if not isinstance(published, list) or manifest not in published:
            raise _storage_shared_1.AttachmentNotFoundError('attachment is not published in this room')
        unavailable = conn.scalar(select(retired.c.room_id).where(room_repo.scope(retired, store, room_id))) is not None
        if unavailable:
            raise _storage_shared_1.AttachmentNotFoundError('Group Chat is unavailable to viewers')
    recipients = json.loads(row['recipient_member_ids_json'])
    if viewer:
        if row['viewer_access'] != 1:
            raise _storage_shared_1.AttachmentNotFoundError('attachment is unavailable to Group Chat viewers')
    elif recipient_member_id not in recipients:
        raise _storage_shared_1.AttachmentNotFoundError('attachment is unavailable to this recipient')
    return row

def select_committed(store, *, authority=None, **selection):
    with store.read() as conn:
        if authority is not None:
            viewer_room(conn, store, **authority)
        return committed_row(conn, store, **selection)

def reconcile(store, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        joined = attachments.join(events, (events.c.store_id == attachments.c.store_id) & (events.c.room_id == attachments.c.room_id) & (events.c.event_id == func.convert_to(attachments.c.event_id, 'UTF8')))
        rows = conn.execute(select(attachments.c.attachment_id, events.c.payload_json).select_from(joined).where(room_repo.scope(attachments, store), attachments.c.state == 'committed', attachments.c.expires_at.is_not(None))).mappings()
        changed = 0
        for row in rows:
            try:
                payload = json.loads(bytes(row['payload_json']))
                ids = {str(item.get('attachment_id') or '') for item in payload.get('attachments', []) if isinstance(item, dict)}
            except (ValueError, TypeError, AttributeError, RecursionError):
                continue
            if row['attachment_id'] in ids:
                changed += conn.execute(update(attachments).where(room_repo.key(attachments, store, dict(attachment_id=row['attachment_id'])), attachments.c.state == 'committed').values(expires_at=None, updated_at=now)).rowcount
        return changed

def mark_disbanded(store, room_id, now):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        return conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.state != 'disbanded').values(state='disbanded', updated_at=now, expires_at=now + _storage_shared_1.DISBANDED_GRACE_SECONDS)).rowcount

def prune(store, *, now, namespace):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
        room_rows = conn.execute(select(rooms.c.room_id, rooms.c.disbanded_at).where(room_repo.scope(rooms, store), rooms.c.disbanded_at.is_not(None)))
        tombstones = dict(room_rows.all())
        tombstones.update(dict(conn.execute(select(retired.c.room_id, retired.c.retired_at).where(room_repo.scope(retired, store))).all()))
        for room_id, timestamp in tombstones.items():
            conn.execute(update(attachments).where(room_repo.scope(attachments, store, room_id), attachments.c.state == 'committed').values(state='disbanded', updated_at=now, expires_at=timestamp + _storage_shared_1.DISBANDED_GRACE_SECONDS))
        expired = room_repo.scope(attachments, store) & attachments.c.expires_at.is_not(None) & (attachments.c.expires_at <= now)
        rows = conn.execute(select(attachments.c.attachment_id, attachments.c.blob_id).where(expired)).mappings().all()
        released = Counter(row['blob_id'] for row in rows)
        conn.execute(delete(attachments).where(expired))
        for blob_id, count in released.items():
            row = _blob_row(conn, store, blob_id=blob_id)
            if row is None:
                continue
            key = room_repo.key(blobs, store, dict(blob_id=blob_id))
            if row['ref_count'] > count:
                conn.execute(update(blobs).where(key).values(ref_count=blobs.c.ref_count - count))
            else:
                conn.execute(delete(blobs).where(key))
                conn.execute(insert(cleanup).values(store_id=store.scope.require_store_id(), blob_id=blob_id, namespace=namespace, created_at=now).on_conflict_do_nothing())
        return len(rows)

def pending_jobs(store, namespace):
    with store.read() as conn:
        return list(conn.execute(select(cleanup.c.blob_id).where(room_repo.scope(cleanup, store), cleanup.c.namespace == namespace)).scalars())

def complete_job(store, namespace, blob_id):
    with store.write() as conn:
        conn.execute(delete(cleanup).where(room_repo.key(cleanup, store, dict(namespace=namespace, blob_id=blob_id))))

def live_blobs(store):
    with store.write() as conn:
        room_repo.lock_store(conn, store)
    with store.read() as conn:
        return set(conn.execute(select(blobs.c.blob_id).where(room_repo.scope(blobs, store))).scalars())

def namespace(store, now):
    with store.read() as conn:
        value = conn.scalar(select(roots.c.namespace).where(repo.scope(roots, store)))
    if value is not None:
        return value
    candidate = secrets.token_hex(16)
    with store.write() as conn:
        repo.lock_store(conn, store)
        conn.execute(insert(roots).values(store_id=store.scope.require_store_id(), namespace=candidate, created_at=now).on_conflict_do_nothing())
        return conn.scalar(select(roots.c.namespace).where(repo.scope(roots, store)))

def attachment(conn, store, attachment_id=None, *, room_id=None, upload_id=None):
    fields = {key: value for key, value in dict(attachment_id=attachment_id, room_id=room_id, upload_id=upload_id).items() if value is not None}
    row = conn.execute(select(attachments).where(repo.key(attachments, store, fields))).mappings().one_or_none()
    return repo.record(row) if row is not None else None

def _blob_row(conn, store, *, sha256=None, blob_id=None):
    fields = {key: value for key, value in dict(sha256=sha256, blob_id=blob_id).items() if value is not None}
    row = conn.execute(select(blobs).where(repo.key(blobs, store, fields))).mappings().one_or_none()
    return repo.record(row) if row is not None else None

def totals(conn, store, *, room_id=None, state=None, live_only=False):
    statement = select(func.count(), func.coalesce(func.sum(attachments.c.size), 0)).where(repo.scope(attachments, store, room_id))
    if state is not None:
        statement = statement.where(attachments.c.state == state)
    if live_only:
        statement = statement.where(attachments.c.state != 'disbanded')
    count, size = conn.execute(statement).one()
    return (int(count), int(size))

def stats(store, room_id):
    with store.read() as conn:
        count, size = totals(conn, store, room_id=room_id)
        blob_count, physical = conn.execute(select(func.count(), func.coalesce(func.sum(blobs.c.size), 0)).where(repo.scope(blobs, store))).one()
        return dict(attachments=count, logical_bytes=size, blobs=int(blob_count), physical_bytes=int(physical))
