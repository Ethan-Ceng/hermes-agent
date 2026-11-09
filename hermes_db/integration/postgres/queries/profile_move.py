"""Current PG snapshots and runtime-history refusal on the caller's connection."""

from sqlalchemy import select

from hermes_db.domains.sessions.postgres.queries import messages as transcript, retirement, sessions
from hermes_db.tables.conversations import session_model_usage, system_prompts
from hermes_db.tables.runtime import session_admissions, worker_executions
from hermes_state_profile_repair import SessionLedgeredError


def require_unledgered(conn, scope, sid):
    members = retirement.compression_members(conn, scope, [sid])
    for table, column in ((session_admissions, session_admissions.c.target_session_id), (worker_executions, worker_executions.c.session_id)):
        if conn.execute(select(column).where(table.c.store_id == scope.require_store_id(), column.in_(members)).limit(1)).first() is not None:
            raise SessionLedgeredError(sid)
    return members


def snapshot(conn, scope, sid):
    raw = sessions.raw_session(conn, scope, sid)
    if raw is None:
        return None

    def prompt(key):
        return conn.scalar(select(system_prompts.c.prompt).where(system_prompts.c.store_id == scope.require_store_id(),
            system_prompts.c.hash == key)) if key else None

    usage = [{key: value for key, value in row.items() if key != "store_id"} for row in conn.execute(select(session_model_usage).where(
        session_model_usage.c.store_id == scope.require_store_id(), session_model_usage.c.session_id == sid).order_by(
            session_model_usage.c.model, session_model_usage.c.billing_provider, session_model_usage.c.billing_base_url,
            session_model_usage.c.billing_mode, session_model_usage.c.task)).mappings()]
    return {"session": {key: value for key, value in raw.items() if key != "store_id"},
        "system_prompt": prompt(raw["system_prompt_hash"]), "tool_pin": prompt(raw["tool_names"]),
        "messages": transcript.select_rows(conn, scope, [sid]), "usage": usage}
