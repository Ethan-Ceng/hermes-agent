"""Attachment units of work also fence the captured content-dataset generation."""

from contextlib import contextmanager
from sqlalchemy import select
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.rooms.postgres.queries import rooms as repo
from hermes_db.tables.room_attachments import roots


class AttachmentResource:
    def __init__(self, resource, namespace):
        self._resource, self.namespace = resource, namespace
        self.scope = resource.scope

    def _check(self, conn, *, lock=False):
        statement = select(roots.c.namespace).where(repo.scope(roots, self))
        current = conn.scalar(statement.with_for_update(read=True) if lock else statement)
        if current != self.namespace:
            raise StorageConfigurationError("Captured room attachment dataset changed; reopen its owning store")

    @contextmanager
    def read(self):
        with self._resource.read() as conn:
            self._check(conn)
            yield conn

    @contextmanager
    def write(self):
        with self._resource.write() as conn:
            repo.lock_store(conn, self)
            self._check(conn, lock=True)
            yield conn
