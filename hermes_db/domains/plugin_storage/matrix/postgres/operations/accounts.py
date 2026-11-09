"""Matrix account, sync, device lists and signatures are scoped short operations."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from hermes_db.domains.plugin_storage.matrix.postgres.queries import crypto as repo
from hermes_db.tables.matrix_crypto import roots, olm_sessions, outbound, tracked_users, devices, cross_signing, signatures, message_indices
from hermes_db.core.values import encode_text


def account(conn, reference):
    return repo.row(conn, reference, roots)


def put_account(conn, reference, *, pickle, shared, identity_key):
    from hermes_db.errors import StorageConflictError
    current = account(conn, reference)
    if current["identity_key"] not in (None, identity_key):
        raise StorageConflictError("Matrix device already owns a different encryption identity")
    repo.change(conn, reference, roots, {}, dict(account_pickle=pickle, shared=int(shared), identity_key=identity_key))


def put_device_id(conn, reference, *, device_id):
    from hermes_db.errors import StorageConfigurationError
    if device_id != reference.owner_device:
        raise StorageConfigurationError("Matrix device identity differs from its captured encryption scope; open a new device store")
    repo.change(conn, reference, roots, {}, {"device_id": device_id})


def put_next_batch(conn, reference, *, next_batch):
    repo.change(conn, reference, roots, {}, {"sync_token": next_batch})


def delete_account(conn, reference):
    # mautrix 0.21.1 delete preserves inbound history and remote-device trust.
    for table in (olm_sessions, outbound):
        conn.execute(delete(table).where(repo.scope(table, reference)))
    repo.change(conn, reference, roots, {}, dict(account_pickle=None, identity_key=None, shared=0, device_id=None, sync_token=None))


def get_devices(conn, reference, *, user_id):
    if repo.row(conn, reference, tracked_users, {"user_id": user_id}) is None:
        return None
    return [repo.decode(row) for row in conn.execute(select(devices).where(repo.key(devices, reference, {"user_id": user_id})).order_by(devices.c.device_id)).mappings()]


def get_device(conn, reference, **fields):
    row = conn.execute(select(devices).where(repo.key(devices, reference, fields)).order_by(devices.c.device_id).limit(1)).mappings().first()
    return repo.decode(row)


def put_devices(conn, reference, *, user_id, records):
    repo.upsert(conn, reference, tracked_users, {"user_id": user_id})
    conn.execute(delete(devices).where(repo.key(devices, reference, {"user_id": user_id})))
    for record in records:
        repo.upsert(conn, reference, devices, record)


def filter_tracked_users(conn, reference, *, users):
    existing = set(conn.scalars(select(tracked_users.c.user_id).where(repo.scope(tracked_users, reference), tracked_users.c.user_id.in_([encode_text(user) for user in users]))))
    return [user for user in users if encode_text(user) in existing]


def put_cross_signing_key(conn, reference, *, user_id, usage, key):
    repo.upsert(conn, reference, cross_signing, dict(user_id=user_id, usage=usage, key=key, first_key=key), preserve=("first_key",))


def get_cross_signing_keys(conn, reference, *, user_id):
    return [repo.decode(row) for row in conn.execute(select(cross_signing).where(repo.key(cross_signing, reference, {"user_id": user_id}))).mappings()]


def put_signature(conn, reference, *, fields, signature):
    repo.upsert(conn, reference, signatures, dict(fields, signature=signature))


def is_key_signed_by(conn, reference, *, fields):
    return repo.row(conn, reference, signatures, fields) is not None


def drop_signatures_by_key(conn, reference, *, user_id, key):
    return conn.execute(delete(signatures).where(repo.key(signatures, reference, {"signer_user": user_id, "signer_key": key}))).rowcount


def validate_message_index(conn, reference, *, sender_key, session_id, event_id, index, timestamp):
    identity = dict(sender_key=sender_key, session_id=session_id, message_index=index)
    conn.execute(insert(message_indices).values(store_id=reference.store_id, account_key=encode_text(reference.account_key), owner_device=encode_text(reference.owner_device),
        **repo.values(message_indices, dict(identity, event_id=event_id, timestamp=timestamp))).on_conflict_do_nothing())
    row = repo.row(conn, reference, message_indices, identity)
    return row["event_id"] == event_id and row["timestamp"] == timestamp
