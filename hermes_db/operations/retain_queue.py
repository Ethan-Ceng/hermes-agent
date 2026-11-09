"""Stable pending requests and token-fenced send/ack/failure transactions."""

import hashlib
import json
import uuid
from contextlib import nullcontext
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.retain_queue import open_queue, WorkerRetainQueueRef
from hermes_db.errors import StorageConflictError
from hermes_db.tables.retain_queue import pending
from hermes_db.core.values import decode_text, encode_text

LEASE_SECONDS = 120
TEXT_FIELDS = frozenset({"user_id", "session_id", "messages_json", "last_error"})


def _unit(reference, *, write=False, connection=None):
    # The authenticated worker effect already owns the receipt's exact Core transaction.
    return nullcontext(connection) if connection is not None else open_queue(reference, write=write)


def scope(reference, *, destination=True):
    base = and_(pending.c.store_id == reference.store_id, pending.c.plugin_id == reference.plugin_id)
    return and_(base, pending.c.destination_id == reference.destination_id) if destination else base


def key(reference, request_id, *, destination=True):
    return and_(scope(reference, destination=destination), pending.c.request_id == request_id)


def now(conn):
    return float(conn.scalar(select(func.extract("epoch", func.clock_timestamp()))))


def decode(row):
    return None if row is None else {name: decode_text(value) if name in TEXT_FIELDS else value for name, value in row.items()}


def prepare(reference, request_id, user_id, session_id, messages):
    body = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(json.dumps([reference.destination_id, user_id, session_id, body], ensure_ascii=True, separators=(",", ":")).encode()).digest()
    return dict(request_id=request_id, destination_id=reference.destination_id, fingerprint=digest,
        user_id=encode_text(user_id), session_id=encode_text(session_id), messages_json=encode_text(body))


def enqueue(reference, record, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        if record['destination_id'] != reference.destination_id:
            raise StorageConflictError('RetainDB enqueue destination changed')
        return reference.command('enqueue', request_id=record['request_id'], user_id=decode_text(record['user_id']),
            session_id=decode_text(record['session_id']), messages=json.loads(decode_text(record['messages_json'])))
    with _unit(reference, write=True, connection=connection) as conn:
        conn.execute(insert(pending).values(store_id=reference.store_id, plugin_id=reference.plugin_id, created_at=now(conn), **record)
            .on_conflict_do_nothing(index_elements=list(pending.primary_key.columns)))
        row = conn.execute(select(pending).where(key(reference, record["request_id"], destination=False))).mappings().one()
        if row["destination_id"] != record["destination_id"] or bytes(row["fingerprint"]) != record["fingerprint"]:
            raise StorageConflictError("RetainDB request identity was reused for different content or destination")
        return decode(row)


def _eligible(stamp):
    return or_(and_(pending.c.status == "pending", pending.c.next_attempt_at <= stamp),
               and_(pending.c.status == "claimed", pending.c.lease_until <= stamp))


def ready(reference, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('ready')
    with _unit(reference, connection=connection) as conn:
        return conn.scalar(select(pending.c.request_id).where(scope(reference), _eligible(now(conn))).limit(1)) is not None


def claim(reference, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('claim') if ready(reference) else None
    with _unit(reference, write=True, connection=connection) as conn:
        stamp = now(conn)
        row = conn.execute(select(pending).where(scope(reference), _eligible(stamp)).order_by(pending.c.sequence).limit(1)
            .with_for_update(skip_locked=True)).mappings().one_or_none()
        if row is None:
            return None
        token = str(uuid.uuid4())
        changes = dict(status="claimed", claim_token=token, lease_until=stamp + LEASE_SECONDS, attempts=row["attempts"] + 1)
        conn.execute(update(pending).where(key(reference, row["request_id"])).values(**changes))
        return decode(dict(row, **changes))


def renew(reference, request_id, token, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('renew', request_id=request_id, token=token)
    with _unit(reference, write=True, connection=connection) as conn:
        stamp = now(conn)
        return conn.execute(update(pending).where(key(reference, request_id), pending.c.status == "claimed", pending.c.claim_token == token,
            pending.c.lease_until > stamp).values(lease_until=stamp + LEASE_SECONDS)).rowcount == 1


def owns_claim(reference, request_id, token, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('owns_claim', request_id=request_id, token=token)
    with _unit(reference, connection=connection) as conn:
        return conn.scalar(select(pending.c.request_id).where(key(reference, request_id), pending.c.status == 'claimed',
            pending.c.claim_token == token, pending.c.lease_until > now(conn))) is not None


def acknowledge(reference, request_id, token, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('acknowledge', request_id=request_id, token=token)
    with _unit(reference, write=True, connection=connection) as conn:
        return conn.execute(update(pending).where(key(reference, request_id), pending.c.status == "claimed", pending.c.claim_token == token).values(
            status="acknowledged", acknowledged_at=now(conn), user_id=None, session_id=None, messages_json=None, last_error=None,
            claim_token=None, lease_until=None)).rowcount == 1


def fail(reference, request_id, token, error, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.command('fail', request_id=request_id, token=token, error=error)
    with _unit(reference, write=True, connection=connection) as conn:
        row = conn.execute(select(pending.c.attempts).where(key(reference, request_id), pending.c.status == "claimed", pending.c.claim_token == token).with_for_update()).one_or_none()
        if row is None:
            return False
        return conn.execute(update(pending).where(key(reference, request_id), pending.c.status == "claimed", pending.c.claim_token == token).values(
            status="pending", next_attempt_at=now(conn) + min(60, 2 ** min(int(row[0]), 6)), last_error=encode_text(error), claim_token=None, lease_until=None)).rowcount == 1


def inspect(reference, request_id, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('inspect', request_id=request_id)
    with _unit(reference, connection=connection) as conn:
        return decode(conn.execute(select(pending).where(key(reference, request_id))).mappings().one_or_none())


def counts(reference, *, connection=None):
    if isinstance(reference, WorkerRetainQueueRef):
        return reference.query('counts')
    with _unit(reference, connection=connection) as conn:
        rows = conn.execute(select(pending.c.destination_id, pending.c.status, func.count()).where(scope(reference, destination=False))
            .group_by(pending.c.destination_id, pending.c.status)).all()
        return dict(pending=sum(count for destination, status, count in rows if destination == reference.destination_id and status != "acknowledged"),
            other_destination=sum(count for destination, status, count in rows if destination != reference.destination_id and status != "acknowledged"),
            acknowledged=sum(count for destination, status, count in rows if destination == reference.destination_id and status == "acknowledged"))
