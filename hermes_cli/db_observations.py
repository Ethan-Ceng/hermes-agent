"""Named read-only operational observations; the caller supplies the owning Profile."""

from contextlib import contextmanager


@contextmanager
def _read(home, expected_identity=None):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.errors import StorageConfigurationError
    with _owning_profile(home), acquire_profile_domain("sessions", profile_home=home) as resource:
        if resource.settings.backend != "postgresql":
            raise StorageConfigurationError("PG observations require the Profile PostgreSQL backend")
        if expected_identity is not None:
            from hermes_db.core.values import resource_key
            if (resource.scope.store_id, resource_key(resource._transactions)) != expected_identity:
                raise StorageConfigurationError("Captured operational database identity changed")
        with resource.read() as conn:
            yield conn, resource.scope.require_store_id()


def has_messages(home):
    from hermes_db.domains.observations import has_messages as query
    with _read(home) as (conn, store_id):
        return query(conn, store_id)


def approval_history_rows(home, since):
    from hermes_db.domains.observations import approval_history_rows as query
    with _read(home) as (conn, store_id):
        return query(conn, store_id, since)


def worktree_sessions(home, store_id, target):
    from hermes_db.domains.observations import worktree_sessions as query
    with _read(home, (store_id, target)) as (conn, owned):
        return query(conn, owned)


def terminal_execution(reference, execution_id, generation):
    from hermes_db.domains.observations import terminal_execution as query
    with _read(reference["home"], (reference["store_id"], reference["target"])) as (conn, owned):
        return query(conn, owned, execution_id, generation)


def cron_writers(home):
    from hermes_db.domains.observations import cron_writers as query
    with _read(home) as (conn, owned):
        return query(conn, owned)


def kanban_due_board(home, statuses):
    from hermes_db.domains.observations import kanban_due_board as query
    with _read(home) as (conn, owned):
        return query(conn, owned, statuses)
