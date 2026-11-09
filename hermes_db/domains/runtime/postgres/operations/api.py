"""Body LRU and durable request settlement share the caller's transaction."""

import json

from sqlalchemy import func, literal, select

from hermes_db.domains.runtime.postgres.queries import api as repo
from hermes_db.tables.api import conversations, responses, response_keys, response_admissions
from hermes_db.tables.runtime import session_admissions, state_meta
from hermes_state_terminal import ADMISSION_PREFIX


def resolve_admission(conn, scope, api_scope, key, request_id):
    from hermes_db.domains.runtime.postgres.queries import runtime, terminal
    from hermes_state_runtime import RuntimeStoreError

    admission_id = repo.admission(conn, scope, api_scope, key)
    if admission_id:
        row = runtime.admission(conn, scope, admission_id)
        if row is None:
            raise RuntimeStoreError("admission_conflict")
    else:
        matches = [dict(row) for row in conn.execute(select(session_admissions).where(
            session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.principal_id == "api",
            session_admissions.c.request_id == request_id)).mappings()]
        matches.extend(terminal.api_admissions(conn, scope, request_id))
        if len(matches) > 1:
            raise RuntimeStoreError("admission_conflict")
        if not matches:
            return None
        row = matches[0]
    if row["principal_id"] != "api" or row["request_id"] != request_id:
        raise RuntimeStoreError("permission_denied")
    if repo.key(conn, scope, api_scope, key) is None:
        raise RuntimeStoreError("admission_conflict")
    repo.bind_admission(conn, scope, api_scope, key, row["admission_id"])
    return runtime.public_row(row)


def settle_keys(conn, scope, api_scope, *, now=None):
    from gateway.platforms.api_server_response_identity import durable_response_id

    # Settlement needs only a canonical status or a retired-key existence
    # proof. Never hydrate the admission's potentially large request/history.
    rows = conn.execute(select(response_keys.c.request_key, response_keys.c.created_at,
        responses.c.data, session_admissions.c.status, state_meta.c.key.label("retired"))
        .outerjoin(response_admissions, (response_admissions.c.store_id == response_keys.c.store_id)
            & (response_admissions.c.api_scope == response_keys.c.api_scope) & (response_admissions.c.request_key == response_keys.c.request_key))
        .outerjoin(responses, (responses.c.store_id == response_keys.c.store_id) & (responses.c.api_scope == response_keys.c.api_scope)
            & (responses.c.response_id == response_keys.c.request_key))
        .outerjoin(session_admissions, (session_admissions.c.store_id == response_admissions.c.store_id)
            & (session_admissions.c.admission_id == response_admissions.c.admission_id))
        .outerjoin(state_meta, (state_meta.c.store_id == response_admissions.c.store_id)
            & (state_meta.c.key == literal(ADMISSION_PREFIX) + response_admissions.c.admission_id))
        .where(repo.where(scope, api_scope, response_keys), response_keys.c.settled_at.is_(None))).all()
    for request_key, created_at, raw, status, retired in rows:
        value = json.loads(raw) if raw is not None else None
        envelope = value.get("response") if isinstance(value, dict) else None
        terminal = status == "terminal" or retired is not None
        if envelope is not None or terminal:
            response_id = envelope.get("id") if isinstance(envelope, dict) else None
            if response_id is None and terminal:
                response_id = durable_response_id(request_key)
            conn.execute(response_keys.update().where(repo.where(scope, api_scope, response_keys), response_keys.c.request_key == request_key)
                .values(settled_at=created_at if now is None else now, response_id=response_id))


def evict(conn, scope, api_scope, max_size, max_identities, now):
    # A newly stored terminal envelope settles its identity even when this
    # same pass evicts its body (including a zero-capacity body cache).
    settle_keys(conn, scope, api_scope, now=now)
    count = conn.scalar(select(func.count()).select_from(responses).where(repo.where(scope, api_scope, responses)))
    if count > max_size:
        ids = conn.execute(select(responses.c.response_id).where(repo.where(scope, api_scope, responses))
            .order_by(responses.c.accessed_at, responses.c.response_id).limit(count - max_size)).scalars().all()
        conn.execute(conversations.delete().where(repo.where(scope, api_scope, conversations), conversations.c.response_id.in_(ids)))
        conn.execute(responses.delete().where(repo.where(scope, api_scope, responses), responses.c.response_id.in_(ids)))
    count = conn.scalar(select(func.count()).select_from(response_keys).where(repo.where(scope, api_scope, response_keys), response_keys.c.settled_at.is_not(None)))
    if count > max_identities:
        keys = conn.execute(select(response_keys.c.request_key).where(repo.where(scope, api_scope, response_keys), response_keys.c.settled_at.is_not(None))
            .order_by(response_keys.c.settled_at, response_keys.c.created_at, response_keys.c.request_key).limit(count - max_identities)).scalars().all()
        repo.forget_keys(conn, scope, api_scope, keys)


def delete(conn, scope, api_scope, response_id, now):
    conn.execute(conversations.delete().where(repo.where(scope, api_scope, conversations), conversations.c.response_id == response_id))
    removed = conn.execute(responses.delete().where(repo.where(scope, api_scope, responses), responses.c.response_id == response_id)).rowcount
    settle_keys(conn, scope, api_scope, now=now)
    keys = conn.execute(select(response_keys.c.request_key).where(repo.where(scope, api_scope, response_keys),
        response_keys.c.settled_at.is_not(None), response_keys.c.response_id == response_id)).scalars().all()
    repo.forget_keys(conn, scope, api_scope, keys)
    return bool(removed or keys)
