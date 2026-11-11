"""Native SQLite implements the public portable record contract."""

import pytest
from plugins.plugin_storage import plugin_store, initialize_plugin_store
from tests.plugins.portable_storage_contracts import assert_invalid_values, assert_portable_records


@pytest.fixture(autouse=True)
def portable_schema():
    for name in ['portable', 'other', 'validation', 'expiry', 'key-quota']:
        initialize_plugin_store(name)


def test_portable_records_scope_cas_pagination_and_values():
    assert_portable_records(plugin_store)
    assert_invalid_values(plugin_store("validation"))


def test_expired_records_cannot_reuse_revisions():
    store = plugin_store("expiry")
    first = store.put("expired", "value", ttl_seconds=60)
    with store._connection(write=True) as conn:
        conn.execute("UPDATE plugin_records SET expires_at=0 WHERE namespace=? AND key=?", (store.namespace, b"expired"))
    assert store.get("expired") is None
    assert store.prune_expired(limit=1) == 1
    assert store.put("expired", "new", expected_revision=0).revision > first.revision


def test_native_key_quota_uses_all_retained_rows():
    import pytest
    from plugins.plugin_storage import PluginStorageQuotaError
    from plugins.plugin_storage_types import MAX_NAMESPACE_KEYS
    store = plugin_store("key-quota")
    first = store.put("original", 0)
    with store._connection(write=True) as conn:
        conn.executemany("INSERT INTO plugin_records(namespace,key,value,revision) VALUES(?,?,?,?)",
            [(store.namespace, f"key-{index:04d}".encode(), b"0", index + 2) for index in range(MAX_NAMESPACE_KEYS - 1)])
        conn.execute("UPDATE plugin_namespaces SET revision=? WHERE namespace=?", (MAX_NAMESPACE_KEYS, store.namespace))
    with pytest.raises(PluginStorageQuotaError):
        store.put("overflow", False)
    assert store.delete("original", expected_revision=first.revision)
    assert store.put("overflow", False).revision == MAX_NAMESPACE_KEYS + 1
