"""Responses records and request identities, always bound to store and API scope."""

import json

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.tables.api import conversations, responses, response_keys, response_admissions, response_output_order
from hermes_db.domains.runtime.values import RuntimeStoreError


def where(scope, api_scope, table):
    return and_(table.c.store_id == scope.require_store_id(), table.c.api_scope == api_scope)


def key(conn, scope, api_scope, request_key):
    row = conn.execute(select(response_keys).where(where(scope, api_scope, response_keys),
        response_keys.c.request_key == request_key)).mappings().one_or_none()
    return dict(row) if row else None


def bind_key(conn, scope, api_scope, request_key, fingerprint, model, now):
    conn.execute(insert(response_keys).values(store_id=scope.require_store_id(), api_scope=api_scope, request_key=request_key,
        fingerprint=fingerprint, model_json=json.dumps(model), created_at=int(now)).on_conflict_do_nothing(index_elements=list(response_keys.primary_key.columns)))
    return key(conn, scope, api_scope, request_key)["fingerprint"] == fingerprint


def body(conn, scope, api_scope, response_id):
    return conn.scalar(select(responses.c.data).where(where(scope, api_scope, responses), responses.c.response_id == response_id))


def put(conn, scope, api_scope, response_id, encoded, now):
    statement = insert(responses).values(store_id=scope.require_store_id(), api_scope=api_scope, response_id=response_id, data=encoded, accessed_at=now)
    if response_id.startswith("idem:"):
        statement = statement.on_conflict_do_nothing(index_elements=list(responses.primary_key.columns))
    else:
        statement = statement.on_conflict_do_update(index_elements=list(responses.primary_key.columns), set_={"data": encoded, "accessed_at": now})
    conn.execute(statement)


def forget_keys(conn, scope, api_scope, keys):
    if keys:
        conn.execute(responses.delete().where(where(scope, api_scope, responses), responses.c.response_id.in_(keys)))
        conn.execute(response_keys.delete().where(where(scope, api_scope, response_keys), response_keys.c.request_key.in_(keys)))


def admission(conn, scope, api_scope, request_key):
    return conn.scalar(select(response_admissions.c.admission_id).where(where(scope, api_scope, response_admissions),
        response_admissions.c.request_key == request_key))


def bind_admission(conn, scope, api_scope, request_key, admission_id):
    if key(conn, scope, api_scope, request_key) is None:
        raise RuntimeStoreError("admission_conflict")
    conn.execute(insert(response_admissions).values(store_id=scope.require_store_id(), api_scope=api_scope,
        request_key=request_key, admission_id=admission_id).on_conflict_do_nothing(index_elements=list(response_admissions.primary_key.columns)))
    if admission(conn, scope, api_scope, request_key) != admission_id:
        raise RuntimeStoreError("admission_conflict")


def output_index(conn, scope, api_scope, request_key, item_id):
    if key(conn, scope, api_scope, request_key) is None:
        raise RuntimeStoreError("admission_conflict")
    table = response_output_order
    condition = (where(scope, api_scope, table), table.c.request_key == request_key)
    existing = conn.scalar(select(table.c.output_index).where(*condition, table.c.item_id == item_id))
    if existing is not None:
        return existing
    index = conn.scalar(select(func.coalesce(func.max(table.c.output_index) + 1, 0)).where(*condition))
    conn.execute(insert(table).values(store_id=scope.require_store_id(), api_scope=api_scope, request_key=request_key,
        item_id=item_id, output_index=index))
    return index


def set_conversation(conn, scope, api_scope, name, response_id):
    statement = insert(conversations).values(store_id=scope.require_store_id(), api_scope=api_scope, name=name, response_id=response_id)
    conn.execute(statement.on_conflict_do_update(index_elements=list(conversations.primary_key.columns), set_={"response_id": response_id}))
