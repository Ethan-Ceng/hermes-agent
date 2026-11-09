"""Room coordination captures the canonical Profile's selected storage target."""

from contextlib import contextmanager
from pathlib import Path

from hermes_db.health import is_postgresql_store, profile_home_for_store
from hermes_state_runtime import RuntimeStoreError


def coordination_path(db):
    if not is_postgresql_store(db):
        return Path(db.db_path)
    from hermes_db.domains.rooms import room_reference
    return room_reference(db)


class RoomCoordination:
    def __init__(self, authority):
        self.authority = authority
        self.native = is_postgresql_store(authority.db)
        if not self.native:
            self.path = coordination_path(authority.db)
            return
        self.store_id = authority.db.scope.require_store_id()
        self.path = coordination_path(authority.db)
        self.check_epoch()
        self._prepare()

    def check_epoch(self):
        if self.native:
            from hermes_db.integration.runtime_access import runtime_for_store
            runtime_for_store(self.authority.db).check_epoch(self.authority.epoch)

    def _prepare(self):
        from hermes_db.domains.rooms import capture_room_store
        if capture_room_store(profile_home_for_store(self.authority.db)) != self.path:
            raise RuntimeStoreError("profile_mismatch")

    @contextmanager
    def read(self):
        if not self.native:
            with self.authority.db._read_ctx() as conn:
                yield conn
            return
        raise TypeError("PG room coordination requires a named Core operation")

    def write(self, callback):
        if not self.native:
            return self.authority.db._execute_write(callback)
        raise TypeError("PG room coordination requires a named Core operation")

    def core_read(self, operation, *args):
        from hermes_db.repositories.runtime import require_epoch
        with self.authority.db._transactions.read() as conn:
            require_epoch(conn, self.authority.db.scope, self.authority.epoch)
            return operation(conn, self.authority.db.scope, *args)

    def core_authorize(self, subject, room_id, *, create=False, conn=None):
        from hermes_db.operations.room_coordination import authorize_room
        if conn is not None:
            return authorize_room(conn, self.authority.db, self.authority.epoch, subject, room_id, create=create)
        with self.authority.db._transactions.write() as connection:
            return authorize_room(connection, self.authority.db, self.authority.epoch, subject, room_id, create=create)

    def owner_effect(self, subject, room_id):
        from hermes_db.operations.effects import CoreEffect
        def apply(conn, scope):
            if scope != self.authority.db.scope:
                raise RuntimeStoreError("profile_mismatch")
            return self.core_authorize(subject, room_id, create=True, conn=conn)
        return CoreEffect(apply)


class HostedMemberAuthorization:
    """Captured member capability; file-backed serving checks finish before borrowing SQL."""

    def __init__(self, coordination, *, available, owner, binding, member, profile):
        self.coordination, self.available = coordination, available
        self.values = dict(owner_subject=owner, binding=binding, member_id=member, profile=profile)

    def apply(self, conn, scope, operation, identity, generation):
        from hermes_db.operations.room_coordination import member_authorized
        authority = self.coordination.authority
        if scope != authority.db.scope:
            return False
        return member_authorized(conn, authority.db, authority.epoch,
            operation=operation, identity=identity, generation=generation, **self.values)

    def __call__(self, operation, identity, generation):
        if not self.available():
            return False
        with self.coordination.authority.db._transactions.read() as conn:
            return self.apply(conn, self.coordination.authority.db.scope, operation, identity, generation)


class HostedAdmissionAuthorizer:
    def __init__(self, coordination, authorize):
        self.coordination, self.authorize = coordination, authorize

    def for_task(self, identity, generation):
        return HostedAdmissionFence(self.coordination, self.authorize, identity, generation)


class HostedAdmissionFence:
    def __init__(self, coordination, authorize, identity, generation):
        self.coordination, self.authorize = coordination, authorize
        self.identity, self.generation = identity, generation
        self.prepared = False

    @contextmanager
    def context(self):
        self.prepared = bool(self.authorize.available())
        try:
            yield
        finally:
            self.prepared = False

    def effect(self):
        from hermes_db.operations.effects import CoreEffect
        return CoreEffect(self.apply)

    def apply(self, conn, scope):
        if (not self.prepared or scope.store_id != self.coordination.store_id
                or self.authorize.apply(conn, scope, "submit", self.identity, self.generation) is not True):
            raise RuntimeStoreError("permission_denied")
