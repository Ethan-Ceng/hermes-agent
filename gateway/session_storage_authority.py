"""Existing owner authorization, before database access where required."""

from hermes_db.health import is_postgresql_store
from hermes_db.domains.runtime.access import runtime_for_store

def authorize_history(authority, actor, session_id):
    if is_postgresql_store(authority.db):
        native = getattr(authority, "_native_legacy_transports", {}).get(actor.transport_id) == actor
        return runtime_for_store(authority.db).authorize_history(actor, session_id, native_transport=native)
    from gateway.session_local_migration import require_history_claim
    from hermes_state_mutation_binding import authorize_history as sqlite_authorize
    with authority.db._read_ctx() as conn:
        require_history_claim(authority, conn, actor, session_id)
        return sqlite_authorize(conn, actor, session_id)


def commit_local_session(db, *, epoch, receipt):
    if is_postgresql_store(db):
        return runtime_for_store(db).commit_local_session(epoch=epoch, receipt=receipt)
    from hermes_state_local import commit_local_session as sqlite_commit
    return sqlite_commit(db, epoch=epoch, receipt=receipt)
