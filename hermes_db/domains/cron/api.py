"""Profile-bound Cron entrypoints; legacy path overrides never select a backend."""

from functools import wraps


_POSTGRES_MODULES = {
    "executions": 'hermes_db.domains.cron.postgres.executions',
    "incidents": 'hermes_db.domains.cron.postgres.executions',
    "delivery": 'hermes_db.domains.cron.postgres.delivery',
    "notepad": 'hermes_db.domains.cron.postgres.notepad',
}


def domain_operation(topic, *, domain="cron_executions"):
    def decorate(sqlite_operation):
        @wraps(sqlite_operation)
        def operation(*args, **kwargs):
            from hermes_cli.db_setup import resolve_db_configuration
            settings, scope = resolve_db_configuration()
            if settings.backend == "sqlite":
                return sqlite_operation(*args, **kwargs)
            from importlib import import_module
            from hermes_db.factory import acquire_domain
            with acquire_domain(domain, settings, scope) as resource:
                implementation = import_module(_POSTGRES_MODULES[topic])
                return getattr(implementation, sqlite_operation.__name__)(resource, *args, **kwargs)
        return operation
    return decorate


from hermes_db.core.resource import DomainResource


class CronResource(DomainResource):
    def __init__(self, name, settings, scope, *, transactions, executions, incidents, delivery, notes):
        super().__init__(name, settings, scope, transactions=transactions)
        self.executions = executions
        self.incidents = incidents
        self.delivery = delivery
        self.notes = notes
