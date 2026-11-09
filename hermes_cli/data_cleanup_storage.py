"""Selected-store data removal, captured before confirmation and fenced before local deletion."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoreRemoval:
    home: Path
    store_id: str
    target: str


def capture_removal(home):
    from hermes_cli.db_setup import _owning_profile, storage_backend, resolve_db_configuration
    with _owning_profile(home):
        if storage_backend(home) == "sqlite":
            return None
        from hermes_db.backends.postgresql.engine import get_engine
        from hermes_db.integration.transfer.move_values import resource_key
        from hermes_db.backends.postgresql.transactions import Transactions
        settings, scope = resolve_db_configuration(home)
        pg = settings.postgresql
        return StoreRemoval(scope.profile_home, scope.require_store_id(), resource_key(Transactions(get_engine(pg), pg.schema)))


def purge_store(captured, *, selected=None):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.errors import StorageConfigurationError
    from hermes_db.factory import acquire_domain, acquire_profile_domain
    from hermes_db.integration.transfer.move_values import resource_key
    from hermes_db.tables import load_metadata
    from hermes_db.tables.rooms import rooms
    from sqlalchemy import update
    from sqlalchemy.sql.ddl import sort_tables
    with _owning_profile(captured.home):
        resource = (acquire_domain("sessions", selected.settings, selected.scope) if selected is not None
                    else acquire_profile_domain("sessions", profile_home=captured.home))
    with resource:
        if (resource.settings.backend != "postgresql" or resource.scope.store_id != captured.store_id
                or resource_key(resource._transactions) != captured.target):
            raise StorageConfigurationError("Selected database identity changed after the removal plan; preserve all local files")
        metadata = load_metadata()
        with resource.write() as conn:
            from hermes_db.domains.sessions.postgres.queries.sessions import lock_store
            lock_store(conn, resource.scope, exclusive=True)
            # Historical room evidence can only be erased after the room is disbanded.
            conn.execute(update(rooms).where(rooms.c.store_id == captured.store_id).values(disbanded_at=0))
            tables = sort_tables(metadata.tables.values(), skip_fn=lambda foreign_key: bool(foreign_key.constraint.deferrable))
            for table in reversed(tables):
                conn.execute(table.delete().where(table.c.store_id == captured.store_id))


def refuse_cron_writers(home, rows):
    from gateway.status import get_process_start_time, _pid_exists
    for row in rows:
        if row.get("handoff_pending"):
            raise RuntimeError(f"cron execution {row['id']} is being handed to a worker; wait for it to finish")
        pid = row["pid"]
        if not _pid_exists(pid):
            continue
        current, recorded = get_process_start_time(pid), row.get("process_started_at")
        if current is None or recorded is None or current == recorded:
            raise RuntimeError(f"cron execution {row['id']} still owns {home} (PID {pid}); stop it before retrying")


def purge_profile_store(home):
    captured = capture_removal(home)
    if captured is not None:
        purge_store(captured)
