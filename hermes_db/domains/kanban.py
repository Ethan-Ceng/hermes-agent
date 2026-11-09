"""Kanban business dispatch and immutable, owner-resolved Board handles."""

from contextlib import contextmanager
from functools import wraps
from importlib import import_module

from hermes_db.core.resource import DomainResource
from hermes_db.errors import StorageConfigurationError


class BoardResource(DomainResource):
    def __init__(self, resource, board_id, slug, *, command=None):
        super().__init__(resource.name, resource.settings, resource.scope, transactions=resource._transactions)
        self.board_id = board_id
        self.slug = slug
        self.command = command

    @contextmanager
    def write(self, *, lock_timeout=None):
        from hermes_cli.kanban_db import _assert_not_delegated_child_mutation
        from hermes_db.repositories.kanban import lock_board
        from hermes_db.operations.kanban_file_jobs import lock_files
        _assert_not_delegated_child_mutation()
        with super().write(lock_timeout=lock_timeout) as conn:
            lock_files(conn, self)
            if self.slug == self.board_id == "default":
                from hermes_db.operations.kanban_boards import _lookup, _registry_lock, _save
                _registry_lock(conn, self)
                row = _lookup(conn, self, self.slug)
                if row is None:
                    _save(conn, self, self.slug, None, False)
                elif row["board_id"] != self.board_id:
                    raise StorageConfigurationError("Default Board owner generation changed")
            lock_board(conn, self)
            if self.command is not None and not self.command.committed:
                self.command.check_replay(conn, self)
            yield conn
        if self.command is not None:
            self.command.after_commit(conn)

    def command_result(self, conn, result):
        return self.command.record(conn, self, result) if self.command is not None else result


def domain_operation(topic):
    def decorate(sqlite_operation):
        @wraps(sqlite_operation)
        def operation(store, *args, **kwargs):
            from hermes_db.domains.kanban_worker import WorkerBoardResource
            if isinstance(store, WorkerBoardResource):
                return store.invoke(sqlite_operation.__name__, args, kwargs)
            if isinstance(store, DomainResource):
                if not isinstance(store, BoardResource) or store.settings.backend != "postgresql":
                    raise StorageConfigurationError("Kanban operations require the selected Board store")
                module = import_module(f"hermes_db.operations.kanban_{topic}")
                from hermes_cli.db_setup import _owning_profile
                from hermes_db.domains.kanban_files import board_files
                with _owning_profile(store.scope.profile_home), board_files(store):
                    return getattr(module, sqlite_operation.__name__)(store, *args, **kwargs)
            return sqlite_operation(store, *args, **kwargs)
        return operation
    return decorate


def profile_operation(sqlite_operation):
    @wraps(sqlite_operation)
    def operation(*args, **kwargs):
        from hermes_cli.db_setup import storage_backend
        if storage_backend() == "postgresql":
            from hermes_db.operations import kanban_boards
            from hermes_db.factory import acquire_profile_domain
            with acquire_profile_domain("kanban_tasks") as resource:
                return getattr(kanban_boards, sqlite_operation.__name__)(resource, *args, **kwargs)
        return sqlite_operation(*args, **kwargs)
    return operation


def owner_scoped_operation(file_operation):
    """Shared file orchestration still binds the resource's owning Profile."""
    @wraps(file_operation)
    def operation(store, *args, **kwargs):
        if isinstance(store, DomainResource):
            if not isinstance(store, BoardResource):
                raise StorageConfigurationError("Kanban file operations require a Board resource")
            store._assert_open()
            from hermes_cli.db_setup import _owning_profile
            from hermes_db.domains.kanban_files import board_files
            with _owning_profile(store.scope.profile_home), board_files(store):
                return file_operation(store, *args, **kwargs)
        return file_operation(store, *args, **kwargs)
    return operation


def connect(board=None):
    from hermes_cli import kanban_db as kb
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.operations.kanban_boards import resolve_board
    slug = kb._explicit_board_slug(board) or kb.get_current_board()
    with acquire_profile_domain("kanban_tasks") as resource:
        board_id = resolve_board(resource, slug)
        return BoardResource(resource, board_id, slug)
