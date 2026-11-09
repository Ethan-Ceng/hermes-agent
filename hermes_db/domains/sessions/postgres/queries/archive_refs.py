"""Scoped bounded archive-name projections; missing evidence is not an empty set."""

from sqlalchemy import select

from hermes_db.tables.conversations import messages
from hermes_db.tables.runtime import session_admissions


def message_names(conn, scope):
    rows = conn.execute(select(messages.c.spillover_names).where(messages.c.store_id == scope.require_store_id(),
        messages.c.spillover_names.is_not(None)).limit(20001)).scalars().all()
    if len(rows) > 20000:
        return None
    names = {name for values in rows for name in values}
    pending = conn.execute(select(session_admissions.c.payload_json).where(
        session_admissions.c.store_id == scope.require_store_id(), session_admissions.c.status != "terminal",
        session_admissions.c.payload_json.contains("spillover", autoescape=True)).limit(20001)).scalars().all()
    if len(pending) > 20000:
        return None
    from tools.tool_result_storage import spillover_names_in_text
    for raw in pending:
        names.update(spillover_names_in_text(raw))
    return names


def referenced_names(conn, scope):
    from hermes_db.errors import StorageError
    from hermes_db.domains.sessions.postgres.queries.file_grants import pins
    names = message_names(conn, scope)
    if names is None:
        return None
    try:
        held, _ = pins(conn, scope)
    except (StorageError, ValueError, TypeError, KeyError):
        return None
    return names | held
