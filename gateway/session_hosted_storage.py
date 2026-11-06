"""Independent room coordination beside a configured canonical session backend."""

from contextlib import closing, contextmanager
from pathlib import Path

from hermes_db.health import is_postgresql_store, profile_home_for_store
from hermes_state_runtime import RuntimeStoreError


def coordination_path(db):
    if not is_postgresql_store(db):
        return Path(db.db_path)
    from hermes_db.move_values import digest, resource_key
    suffix = digest([resource_key(db._transactions), db.scope.require_store_id()])
    return profile_home_for_store(db) / f"hosted-pg-{suffix}.db"


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
            from hermes_db.runtime_access import runtime_for_store
            runtime_for_store(self.authority.db).check_epoch(self.authority.epoch)

    def _prepare(self):
        from gateway.hosted_rooms import _connect
        with closing(_connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS state_meta(key TEXT PRIMARY KEY,value TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS runtime_epoch(singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
                "epoch INTEGER NOT NULL,instance_id TEXT)")
            saved = conn.execute("SELECT value FROM state_meta WHERE key='hermes:hosted-pg-store'").fetchone()
            if saved is not None and saved[0] != self.store_id:
                raise RuntimeStoreError("profile_mismatch")
            conn.execute("INSERT OR IGNORE INTO state_meta(key,value) VALUES('hermes:hosted-pg-store',?)", (self.store_id,))
            old = conn.execute("SELECT epoch FROM runtime_epoch WHERE singleton=1").fetchone()
            if old is not None and old[0] > self.authority.epoch:
                raise RuntimeStoreError("stale_epoch")
            conn.execute("INSERT INTO runtime_epoch(singleton,epoch) VALUES(1,?) ON CONFLICT(singleton) "
                "DO UPDATE SET epoch=excluded.epoch", (self.authority.epoch,))

    @contextmanager
    def read(self):
        if not self.native:
            with self.authority.db._read_ctx() as conn:
                yield conn
            return
        from gateway.hosted_rooms import _read_connection
        self.check_epoch()
        with closing(_read_connection(self.path)) as conn:
            conn.execute("BEGIN")
            yield conn

    def write(self, callback):
        if not self.native:
            return self.authority.db._execute_write(callback)
        from gateway.hosted_rooms import _connect
        self.check_epoch()
        with closing(_connect(self.path)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            return callback(conn)


class HostedAdmissionAuthorizer:
    def __init__(self, coordination, authorize):
        self.coordination, self.authorize = coordination, authorize

    def for_task(self, identity, generation):
        return HostedAdmissionFence(self.coordination, self.authorize, identity, generation)


class HostedAdmissionFence:
    def __init__(self, coordination, authorize, identity, generation):
        self.coordination, self.authorize = coordination, authorize
        self.identity, self.generation = identity, generation
        self.conn = None

    @contextmanager
    def context(self):
        from gateway.hosted_rooms import _connect
        # Acquire before borrowing PG. Only read here; releasing this independent
        # fence cannot roll back an already-committed canonical admission.
        with closing(_connect(self.coordination.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.conn = conn
            try:
                yield
            finally:
                self.conn = None
                conn.rollback()

    def effect(self):
        from hermes_db.operations.effects import CoreEffect
        return CoreEffect(self.apply)

    def apply(self, conn, scope):
        if (self.conn is None or scope.store_id != self.coordination.store_id
                or self.authorize(self.conn, "submit", self.identity, self.generation) is not True):
            raise RuntimeStoreError("permission_denied")
