"""Profile-bound Cron entrypoints; legacy path overrides never select a backend."""

from functools import wraps


def domain_operation(topic):
    def decorate(sqlite_operation):
        @wraps(sqlite_operation)
        def operation(*args, **kwargs):
            from hermes_cli.db_setup import resolve_db_configuration
            settings, scope = resolve_db_configuration()
            if settings.backend == "sqlite":
                return sqlite_operation(*args, **kwargs)
            from importlib import import_module
            from hermes_db.factory import acquire_domain
            with acquire_domain("cron_executions", settings, scope) as resource:
                implementation = import_module(f"hermes_db.operations.cron_{topic}")
                return getattr(implementation, sqlite_operation.__name__)(resource, *args, **kwargs)
        return operation
    return decorate
