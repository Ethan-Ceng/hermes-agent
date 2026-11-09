"""Ordinary authority read gates select explicit native or existing SQLite operations."""

from hermes_db.health import is_postgresql_store
from hermes_db.integration.runtime_access import runtime_for_store


def validate_import(db, payload):
    if is_postgresql_store(db):
        from hermes_db.integration.transfer.portability_values import values
        return values._validate_import_payload(payload)
    return db._validate_import_payload(payload)


def pending_target_ids(db, statuses):
    if is_postgresql_store(db):
        return runtime_for_store(db).pending_target_ids(statuses)
    marks = ','.join('?' for _ in statuses)
    return {row['target_session_id'] for row in db._read_all(
        f'SELECT DISTINCT target_session_id FROM session_admissions WHERE status IN ({marks})', tuple(statuses))}


def import_history_effect(db, actor, session_ids):
    if is_postgresql_store(db):
        from hermes_db.operations.effects import CoreEffect
        from hermes_db.repositories.mutation_binding import import_history_control
        return CoreEffect(lambda conn, scope: import_history_control(conn, scope, actor, session_ids))
    from functools import partial
    from hermes_state_mutation_binding import import_history_control
    return partial(import_history_control, actor=actor, session_ids=session_ids)


def retry_terminal_admission(db, **kwargs):
    if is_postgresql_store(db):
        return runtime_for_store(db).retry_terminal_admission(**kwargs)
    from hermes_state_terminal import retry_terminal_admission as sqlite_retry
    return sqlite_retry(db, **kwargs)


def policy_picks(db, session_id):
    if is_postgresql_store(db):
        return runtime_for_store(db).policy_picks(session_id)
    from hermes_state_mutation_prepared import policy_picks as sqlite_picks
    return sqlite_picks(db, session_id)


def commit_refreshed_policy(db, **kwargs):
    if is_postgresql_store(db):
        return runtime_for_store(db).commit_refreshed_policy(**kwargs)
    from hermes_state_mutation_prepared import commit_refreshed_policy as sqlite_commit
    return sqlite_commit(db, **kwargs)


def prepare_chat_pick(db, **kwargs):
    if is_postgresql_store(db):
        return runtime_for_store(db).prepare_chat_pick(**kwargs)
    from hermes_state_mutation_chat_pick import prepare_chat_pick as sqlite_prepare
    return sqlite_prepare(db, **kwargs)


def commit_chat_pick(db, **kwargs):
    if is_postgresql_store(db):
        return runtime_for_store(db).commit_chat_pick(**kwargs)
    from hermes_state_mutation_chat_pick import commit_chat_pick as sqlite_commit
    return sqlite_commit(db, **kwargs)


def has_mutation_receipt(db, principal_id, session_id, request_id):
    from hermes_state_runtime import _text, mutation_receipt_key
    for value in (principal_id, session_id, request_id):
        _text(value)
    key, _ = mutation_receipt_key(principal_id, session_id, request_id,
        operation="model", payload={}, expected_revision=0)
    return db.get_meta(key) is not None


def local_lineage_owner(db, session_id):
    if is_postgresql_store(db):
        return runtime_for_store(db).local_owner(session_id)
    from hermes_state_local import local_lineage_owner as sqlite_owner
    with db._read_ctx() as conn:
        return sqlite_owner(conn, session_id)


def session_launch_source(db, session_id):
    if is_postgresql_store(db):
        return runtime_for_store(db).session_launch_source(session_id)
    with db._read_ctx() as conn:
        row = conn.execute("SELECT source FROM sessions WHERE id=?", (session_id,)).fetchone()
        return row[0] if row else None


def is_compression_child(db, child):
    if is_postgresql_store(db):
        from hermes_db.core.values import explicit_fork
        parent_id = child.get("parent_session_id")
        if not parent_id or explicit_fork(child):
            return False
        parent = db.get_session(parent_id)
        return bool(parent and parent.get("end_reason") == "compression")
    return db._is_compression_child_row(child)


def history_binding_names(db, saved, actor):
    if is_postgresql_store(db):
        from hermes_db.repositories.mutation_binding import binding_names
        return binding_names(saved, db.scope, actor.subject)
    from hermes_state_mutation_binding import binding_names
    return binding_names(saved, actor.subject)


def authorize_history(authority, actor, session_id):
    if is_postgresql_store(authority.db):
        native = getattr(authority, "_native_legacy_transports", {}).get(actor.transport_id) == actor
        return runtime_for_store(authority.db).authorize_history(actor, session_id, native_transport=native)
    from gateway.session_local_migration import require_history_claim
    from hermes_state_mutation_binding import authorize_history as sqlite_authorize
    with authority.db._read_ctx() as conn:
        require_history_claim(authority, conn, actor, session_id)
        return sqlite_authorize(conn, actor, session_id)
