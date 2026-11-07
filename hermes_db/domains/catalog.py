"""Only implemented domains advertise PG support; imports never load drivers."""

from dataclasses import dataclass

from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class DomainSpec:
    revision: str
    table_modules: tuple[str, ...]


KNOWN_DOMAINS = (
    "sessions", "verification", "projects", "cron_executions", "cron_deliveries", "cron_notepad",
    "kanban_tasks", "kanban_runs", "kanban_workspace", "rooms", "room_attachments", "metrics", "plugins", "discord_recovery", "retain_queue", "matrix_crypto",
)
POSTGRES_DOMAINS = {
    "sessions": DomainSpec("0004_model_markers", ("conversations", "runtime", "gateway", "api")),
    "verification": DomainSpec("0005_verification", ("verification",)),
    "projects": DomainSpec("0006_projects", ("projects",)),
    "cron_executions": DomainSpec("0007_cron_executions", ("cron",)),
    "cron_deliveries": DomainSpec("0008_cron_delivery", ("cron_delivery",)),
    "cron_notepad": DomainSpec("0009_cron_notepad", ("cron_notepad",)),
    "kanban_tasks": DomainSpec("0010_kanban_tasks", ("kanban", "kanban_artifacts", "kanban_dispatch", "kanban_commands", "kanban_workspaces", "kanban_notify", "kanban_file_jobs")),
    "kanban_runs": DomainSpec("0011_kanban_runs", ("kanban", "kanban_artifacts", "kanban_dispatch", "kanban_commands", "kanban_workspaces", "kanban_notify", "kanban_file_jobs")),
    "kanban_workspace": DomainSpec("0018_kanban_imports", ("kanban", "kanban_artifacts", "kanban_dispatch", "kanban_commands", "kanban_workspaces", "kanban_notify", "kanban_file_jobs")),
    "rooms": DomainSpec("0019_room_events", ("rooms", "room_runs", "room_work", "room_policy")),
}


def require_domain(name):
    if name not in KNOWN_DOMAINS:
        raise StorageConfigurationError(f"Unknown storage domain: {name}")


def required_tables(spec):
    from importlib import import_module
    from sqlalchemy import Table

    return {value.name for module in spec.table_modules
            for value in vars(import_module(f"hermes_db.tables.{module}")).values() if isinstance(value, Table)}
