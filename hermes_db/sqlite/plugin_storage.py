"""Portable plugin records on native SQLite; no optional PG dependency required."""

from contextlib import contextmanager
import time
from hermes_cli.db_setup import _owning_profile, storage_backend
from hermes_cli.sqlite_util import open_db, write_txn
from hermes_constants import mkdir_under_hermes_home
from hermes_db.errors import StorageConfigurationError
from plugins import plugin_storage_types as contract


class SQLitePluginStore:
    def __init__(self, plugin_id, namespace, profile_home):
        self.profile_home, self.namespace = profile_home, namespace
        self.path = profile_home / "plugin-data" / plugin_id / "portable.db"
        with self._connection(write=True) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS plugin_namespaces(namespace TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0)")
            conn.execute("CREATE TABLE IF NOT EXISTS plugin_records(namespace TEXT NOT NULL, key BLOB NOT NULL, value BLOB NOT NULL, "
                "revision INTEGER NOT NULL, expires_at REAL, PRIMARY KEY(namespace,key), FOREIGN KEY(namespace) REFERENCES plugin_namespaces(namespace))")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_plugin_records_expiry ON plugin_records(namespace,expires_at)")

    @contextmanager
    def _connection(self, *, write=False):
        with _owning_profile(self.profile_home):
            if storage_backend(self.profile_home) != "sqlite":
                raise StorageConfigurationError("Captured SQLite plugin backend changed; reopen its owning store")
            mkdir_under_hermes_home(self.path.parent)
            conn = open_db(self.path, db_label="plugin portable storage", foreign_keys=True)
            try:
                if write:
                    with write_txn(conn):
                        yield conn
                else:
                    yield conn
            finally:
                conn.close()

    def get(self, key):
        key = contract.validate_key(key)
        with self._connection() as conn:
            return contract.decode_record(conn.execute("SELECT * FROM plugin_records WHERE namespace=? AND key=? "
                "AND (expires_at IS NULL OR expires_at>?)", (self.namespace, key, time.time())).fetchone())

    def put(self, key, value, *, expected_revision=None, ttl_seconds=None):
        key, value = contract.validate_key(key), contract.encode_value(value)
        contract.validate_revision(expected_revision)
        contract.validate_ttl(ttl_seconds)
        with self._connection(write=True) as conn:
            conn.execute("INSERT INTO plugin_namespaces(namespace) VALUES (?) ON CONFLICT(namespace) DO NOTHING", (self.namespace,))
            stamp = time.time()
            conn.execute("DELETE FROM plugin_records WHERE namespace=? AND expires_at<=?", (self.namespace, stamp))
            row = conn.execute("SELECT * FROM plugin_records WHERE namespace=? AND key=?", (self.namespace, key)).fetchone()
            contract.check_revision(row, expected_revision)
            count, size = conn.execute("SELECT count(*),coalesce(sum(length(value)),0) FROM plugin_records WHERE namespace=?", (self.namespace,)).fetchone()
            if count + (row is None) > contract.MAX_NAMESPACE_KEYS or size - (len(row["value"]) if row else 0) + len(value) > contract.MAX_NAMESPACE_BYTES:
                raise contract.PluginStorageQuotaError("Plugin namespace exceeds its retained keys or byte quota")
            revision = conn.execute("SELECT revision FROM plugin_namespaces WHERE namespace=?", (self.namespace,)).fetchone()[0] + 1
            expiry = None if ttl_seconds is None else stamp + ttl_seconds
            conn.execute("INSERT INTO plugin_records(namespace,key,value,revision,expires_at) VALUES(?,?,?,?,?) ON CONFLICT(namespace,key) "
                "DO UPDATE SET value=excluded.value,revision=excluded.revision,expires_at=excluded.expires_at", (self.namespace, key, value, revision, expiry))
            conn.execute("UPDATE plugin_namespaces SET revision=? WHERE namespace=?", (revision, self.namespace))
            return contract.decode_record(dict(key=key, value=value, revision=revision, expires_at=expiry))

    def delete(self, key, *, expected_revision=None):
        key = contract.validate_key(key)
        contract.validate_revision(expected_revision)
        with self._connection(write=True) as conn:
            row = conn.execute("SELECT * FROM plugin_records WHERE namespace=? AND key=? AND (expires_at IS NULL OR expires_at>?)",
                (self.namespace, key, time.time())).fetchone()
            contract.check_revision(row, expected_revision)
            if row is None:
                return False
            conn.execute("DELETE FROM plugin_records WHERE namespace=? AND key=?", (self.namespace, key))
            return True

    def scan(self, *, after=None, prefix="", limit=100):
        after = None if after is None else contract.validate_key(after)
        prefix = contract.validate_key(prefix, empty=True)
        contract.validate_limit(limit)
        predicates, args = ["namespace=?", "(expires_at IS NULL OR expires_at>?)"], [self.namespace, time.time()]
        if after is not None:
            predicates.append("key>?")
            args.append(after)
        if prefix:
            predicates.append("substr(key,1,?)=?")
            args.extend((len(prefix), prefix))
        with self._connection() as conn:
            return [contract.decode_record(row) for row in conn.execute("SELECT * FROM plugin_records WHERE " + " AND ".join(predicates) +
                " ORDER BY key LIMIT ?", [*args, limit]).fetchall()]

    def prune_expired(self, *, limit=200):
        contract.validate_limit(limit)
        with self._connection(write=True) as conn:
            return conn.execute("DELETE FROM plugin_records WHERE namespace=? AND key IN (SELECT key FROM plugin_records WHERE namespace=? "
                "AND expires_at<=? ORDER BY key LIMIT ?)", (self.namespace, self.namespace, time.time(), limit)).rowcount
