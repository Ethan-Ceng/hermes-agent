"""Named read-only operational observations; the caller supplies the owning Profile."""

from contextlib import contextmanager


@contextmanager
def _read(home, expected_identity=None):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.errors import StorageConfigurationError
    with _owning_profile(home), acquire_profile_domain("sessions", profile_home=home) as resource:
        if resource.settings.backend != "postgresql":
            raise StorageConfigurationError("PG observations require the Profile PostgreSQL backend")
        if expected_identity is not None:
            from hermes_db.integration.transfer.move_values import resource_key
            if (resource.scope.store_id, resource_key(resource._transactions)) != expected_identity:
                raise StorageConfigurationError("Captured operational database identity changed")
        with resource.read() as conn:
            yield conn, resource.scope.require_store_id()


def has_messages(home):
    from sqlalchemy import select
    from hermes_db.tables.conversations import messages
    with _read(home) as (conn, store_id):
        return conn.scalar(select(messages.c.id).where(messages.c.store_id == store_id).limit(1)) is not None


def approval_history_rows(home, since):
    from sqlalchemy import select
    from hermes_db.tables.conversations import messages
    from hermes_db.core.values import decode_text
    with _read(home) as (conn, store_id):
        scope = (messages.c.store_id == store_id) & (messages.c.timestamp >= since)
        calls = list(conn.scalars(select(messages.c.tool_calls).where(scope,
            messages.c.role == "assistant", messages.c.tool_calls.is_not(None)).order_by(messages.c.id)))
        results = [(identity, decode_text(content)) for identity, content in conn.execute(
            select(messages.c.tool_call_id, messages.c.content).where(scope, messages.c.role == "tool", messages.c.tool_call_id.is_not(None)))]
    return calls, results


def worktree_sessions(home, store_id, target):
    from sqlalchemy import select, or_
    from hermes_db.tables.conversations import sessions
    from hermes_db.tables.runtime import session_admissions, state_meta
    with _read(home, (store_id, target)) as (conn, owned):
        pending = select(session_admissions.c.admission_id).where(session_admissions.c.store_id == owned,
            session_admissions.c.target_session_id == sessions.c.id, session_admissions.c.status != "terminal").exists()
        rows = [dict(row) for row in conn.execute(select(sessions.c.id, sessions.c.cwd, sessions.c.chat_id, sessions.c.message_count,
            sessions.c.ended_at, pending.label("pending")).where(sessions.c.store_id == owned, sessions.c.cwd.is_not(None))).mappings()]
        meta = list(conn.execute(select(state_meta.c.key, state_meta.c.value).where(state_meta.c.store_id == owned,
            or_(*(state_meta.c.key.startswith(prefix, autoescape=True) for prefix in ("loop:", "heartbeat:", "goal:"))))))
    return rows, meta


def terminal_execution(reference, execution_id, generation):
    from sqlalchemy import select
    from hermes_db.tables.runtime import worker_executions
    with _read(reference["home"], (reference["store_id"], reference["target"])) as (conn, owned):
        return conn.scalar(select(worker_executions.c.status).where(worker_executions.c.store_id == owned,
            worker_executions.c.execution_id == execution_id, worker_executions.c.generation == generation)) == "terminal"


def cron_writers(home):
    from sqlalchemy import select
    from hermes_db.tables.cron import cron_executions
    from hermes_db.repositories.cron import decode
    with _read(home) as (conn, owned):
        return [decode(row) for row in conn.execute(select(cron_executions).where(cron_executions.c.store_id == owned,
            cron_executions.c.status.in_(("claimed", "running")))).mappings()]


def kanban_due_board(home, statuses):
    from sqlalchemy import select
    from hermes_db.tables.kanban import tasks, kanban_boards
    from hermes_db.core.values import encode_text
    with _read(home) as (conn, owned):
        return conn.scalar(select(kanban_boards.c.slug).join(tasks,
            (tasks.c.store_id == kanban_boards.c.store_id) & (tasks.c.board_id == kanban_boards.c.board_id)).where(
            tasks.c.store_id == owned, kanban_boards.c.archived == 0,
            tasks.c.status.in_([encode_text(status) for status in statuses])).limit(1))
