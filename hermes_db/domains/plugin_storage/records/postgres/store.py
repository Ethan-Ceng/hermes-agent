"""Selected PG implementation of the driver-free plugin storage protocol."""

from hermes_db.domains.plugin_storage.records.api import capture_plugin, open_plugin
from hermes_db.domains.plugin_storage.records.postgres.operations import records as operations
from plugins import plugin_storage_types as contract


class PostgresPluginStore:
    def __init__(self, plugin_id, namespace, profile_home):
        self.reference = capture_plugin(plugin_id, namespace, profile_home)

    def get(self, key):
        key = contract.validate_key(key)
        with open_plugin(self.reference) as conn:
            return operations.get(conn, self.reference, key)

    def put(self, key, value, *, expected_revision=None, ttl_seconds=None):
        key, data = contract.validate_key(key), contract.encode_value(value)
        contract.validate_revision(expected_revision)
        contract.validate_ttl(ttl_seconds)
        with open_plugin(self.reference, write=True) as conn:
            return operations.put(conn, self.reference, key, data, expected_revision, ttl_seconds)

    def delete(self, key, *, expected_revision=None):
        key = contract.validate_key(key)
        contract.validate_revision(expected_revision)
        with open_plugin(self.reference, write=True) as conn:
            return operations.remove(conn, self.reference, key, expected_revision)

    def scan(self, *, after=None, prefix="", limit=100):
        after = None if after is None else contract.validate_key(after)
        prefix = contract.validate_key(prefix, empty=True)
        contract.validate_limit(limit)
        with open_plugin(self.reference) as conn:
            return operations.scan(conn, self.reference, after, prefix, limit)

    def prune_expired(self, *, limit=200):
        contract.validate_limit(limit)
        with open_plugin(self.reference, write=True) as conn:
            return operations.prune(conn, self.reference, limit)
