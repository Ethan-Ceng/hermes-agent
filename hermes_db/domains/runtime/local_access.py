"""Current local service calls select the owning runtime, with SQLite behavior retained."""

from hermes_db.health import is_postgresql_store
from hermes_db.domains.runtime.access import runtime_for_store




def local_receipt(db, session_id):
    if is_postgresql_store(db):
        return runtime_for_store(db).local_receipt(session_id)
    from hermes_state_local import local_receipt as sqlite_read
    return sqlite_read(db, session_id)


def handoff_head(db, session_id):
    if is_postgresql_store(db):
        return runtime_for_store(db).handoff_head(session_id)
    from hermes_state_local import handoff_head as sqlite_head
    return sqlite_head(db, session_id)


def end_idle_local_session(db, **kwargs):
    if is_postgresql_store(db):
        return runtime_for_store(db).end_idle_local_session(**kwargs)
    from hermes_state_local import end_idle_local_session as sqlite_end
    return sqlite_end(db, **kwargs)


def validate_local_lineage(db, receipt):
    if is_postgresql_store(db):
        return runtime_for_store(db).validate_local_lineage(receipt)
    from hermes_state_local_lineage import validate_local_lineage as sqlite_validate
    with db._read_ctx() as conn:
        return sqlite_validate(conn, receipt)
