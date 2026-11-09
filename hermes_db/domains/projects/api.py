"""Business-operation dispatch; PG resources never impersonate SQLite connections."""

from functools import wraps

from hermes_db.core.resource import DomainResource
from hermes_db.errors import StorageConfigurationError


def domain_operation(sqlite_operation):
    @wraps(sqlite_operation)
    def operation(store, *args, **kwargs):
        if isinstance(store, DomainResource):
            if store.name != "projects" or store.settings.backend != "postgresql":
                raise StorageConfigurationError("Project operations require the selected Projects store")
            from hermes_db.domains.projects import postgres as projects
            return getattr(projects, sqlite_operation.__name__)(store, *args, **kwargs)
        return sqlite_operation(store, *args, **kwargs)
    return operation


class ProjectResource(DomainResource):
    """A Projects transaction owner with the existing application's value constructors."""
    def __init__(self, settings, scope, *, transactions, project_value, folder_value, now):
        super().__init__("projects", settings, scope, transactions=transactions)
        self.project_value = project_value
        self.folder_value = folder_value
        self.now = now
