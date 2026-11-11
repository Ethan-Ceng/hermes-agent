"""Named operational queries over one selected Connection and store identity."""

def has_messages(conn, store_id):
    from sqlalchemy import select
    from hermes_db.tables.conversations import messages
    return conn.scalar(select(messages.c.id).where(messages.c.store_id == store_id).limit(1)) is not None


def approval_history_rows(conn, store_id, since):
    from sqlalchemy import select
    from hermes_db.tables.conversations import messages
    from hermes_db.core.values import decode_text
    scope = (messages.c.store_id == store_id) & (messages.c.timestamp >= since)
    calls = list(conn.scalars(select(messages.c.tool_calls).where(scope,
        messages.c.role == "assistant", messages.c.tool_calls.is_not(None)).order_by(messages.c.id)))
    results = [(identity, decode_text(content)) for identity, content in conn.execute(
        select(messages.c.tool_call_id, messages.c.content).where(scope, messages.c.role == "tool", messages.c.tool_call_id.is_not(None)))]
    return calls, results


def worktree_sessions(conn, owned):
    from sqlalchemy import select, or_
    from hermes_db.tables.conversations import sessions
    from hermes_db.tables.runtime import session_admissions, state_meta
    pending = select(session_admissions.c.admission_id).where(session_admissions.c.store_id == owned,
        session_admissions.c.target_session_id == sessions.c.id, session_admissions.c.status != "terminal").exists()
    rows = [dict(row) for row in conn.execute(select(sessions.c.id, sessions.c.cwd, sessions.c.chat_id, sessions.c.message_count,
        sessions.c.ended_at, pending.label("pending")).where(sessions.c.store_id == owned, sessions.c.cwd.is_not(None))).mappings()]
    meta = list(conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == owned,
        or_(*(state_meta.c.key.startswith(prefix, autoescape=True) for prefix in ("loop:", "heartbeat:", "goal:"))))))
    return rows, meta


def terminal_execution(conn, owned, execution_id, generation):
    from sqlalchemy import select
    from hermes_db.tables.runtime import worker_executions
    return conn.scalar(select(worker_executions.c.status).where(worker_executions.c.store_id == owned,
        worker_executions.c.execution_id == execution_id, worker_executions.c.generation == generation)) == "terminal"


def cron_writers(conn, owned):
    from sqlalchemy import select
    from hermes_db.tables.cron import cron_executions
    from hermes_db.domains.cron.postgres.executions import _decode as decode
    return [decode(row) for row in conn.execute(select(cron_executions).where(cron_executions.c.store_id == owned,
        cron_executions.c.status.in_(("claimed", "running")))).mappings()]


def kanban_due_board(conn, owned, statuses):
    from sqlalchemy import select
    from hermes_db.tables.kanban import tasks, kanban_boards
    from hermes_db.core.values import encode_text
    return conn.scalar(select(kanban_boards.c.slug).join(tasks,
        (tasks.c.store_id == kanban_boards.c.store_id) & (tasks.c.board_id == kanban_boards.c.board_id)).where(
        tasks.c.store_id == owned, kanban_boards.c.archived == 0,
        tasks.c.status.in_([encode_text(status) for status in statuses])).limit(1))


def first_session_started_at(conn, store_id):
    from sqlalchemy import func, select
    from hermes_db.tables.conversations import sessions
    return conn.scalar(select(func.min(sessions.c.started_at)).where(sessions.c.store_id == store_id))
