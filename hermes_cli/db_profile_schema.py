"""Explicit application lifecycle for selected Profile SQLite datasets."""

from pathlib import Path

from hermes_cli.db_scope import bind_profile_home
from hermes_db.scope import DatabaseScope


def initialize_new_profile_storage(profile_home: Path) -> None:
    from hermes_cli.db_sessions import _owner_only
    from hermes_cli.db_setup import storage_backend
    from hermes_cli.db_session_schema import initialize_new_profile_sessions
    from hermes_cli import projects_db
    from cron.storage_lifecycle import initialize_cron_stores

    _owner_only()
    if storage_backend(profile_home) != "sqlite":
        return
    with bind_profile_home(DatabaseScope(profile_home)):
        initialize_new_profile_sessions(profile_home)
        from gateway.delivery_ledger import initialize as initialize_delivery_ledger
        initialize_delivery_ledger(profile_home / "state.db")
        from gateway import hosted_rooms
        hosted_rooms._initialize_connection(profile_home / "state.db").close()
        if not (profile_home / "projects.db").exists():
            projects_db.initialize_projects(profile_home=profile_home)
        initialize_cron_stores()
        from plugins.plugin_storage import initialize_selected_plugin_stores
        initialize_selected_plugin_stores(profile_home)
        _initialize_kanban_stores()
        _initialize_api_stores(profile_home)
        _initialize_metrics_if_owned(profile_home)


def upgrade_sqlite_profile_storage(scope) -> dict:
    from gateway.runtime_ownership import OwnershipConflict, exclusive_maintenance
    from hermes_cli.db_session_schema import upgrade_sqlite_session_schema
    from hermes_cli import projects_db
    from cron.storage_lifecycle import initialize_cron_stores
    from hermes_db.errors import StorageSchemaError

    try:
        with bind_profile_home(scope):
            from gateway import hosted_rooms
            room_path = hosted_rooms.default_db_path()
            homes = sorted({scope.profile_home, room_path.parent}, key=str)
            with exclusive_maintenance(homes, purpose="db_upgrade"):
                result = upgrade_sqlite_session_schema(scope)
                projects_db.initialize_projects(profile_home=scope.profile_home)
                initialize_cron_stores()
                from gateway.delivery_ledger import initialize as initialize_delivery_ledger

                initialize_delivery_ledger(scope.profile_home / "state.db")
                hosted_rooms._initialize_connection(scope.profile_home / "state.db").close()
                hosted_rooms._initialize_connection(room_path).close()
                from plugins.plugin_storage import initialize_selected_plugin_stores
                initialize_selected_plugin_stores(scope.profile_home)
                _initialize_kanban_stores()
                _initialize_api_stores(scope.profile_home)
                _initialize_metrics_if_owned(scope.profile_home)
                return result
    except OwnershipConflict:
        raise StorageSchemaError("Stop this profile's gateway before running `hermes db upgrade`.") from None


def _initialize_metrics_if_owned(profile_home: Path) -> None:
    from hermes_cli.db_setup import _storage_config

    config = _storage_config(profile_home)
    enabled = ((config.get("telemetry") or {}).get("shared_metrics") or {}).get("enabled") is True
    exists = (profile_home / "telemetry" / "shared_metrics" / "metrics.sqlite3").exists()
    if enabled or exists:
        from hermes_cli.observability.shared_metrics import SharedMetricsStore
        SharedMetricsStore.create(profile_home=profile_home)


def _initialize_api_stores(profile_home):
    from gateway.platforms.api_server_response_store import ResponseStore
    from gateway.platforms.api_server_run_idempotency import RunIdempotencyStore
    ResponseStore(db_path=str(profile_home / 'response_store.db')).close()
    RunIdempotencyStore(db_path=str(profile_home / 'runs_idempotency.db')).close()


def _initialize_kanban_stores():
    from hermes_cli import kanban_db
    for board in kanban_db.list_boards(include_archived=True):
        if not board.get('archived'):
            kanban_db.init_db(board=board['slug'])
