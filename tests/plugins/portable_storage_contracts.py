"""Shared public behavior for portable SQLite and PG plugin stores."""

import pytest
from plugins.plugin_storage import PluginStorageConflict


def assert_portable_records(factory):
    store = factory("portable", namespace="main")
    first = store.put("key\x00🙂", {"zero": 0, "false": False, "none": None, "text": "值\x00"}, expected_revision=0)
    assert factory("portable", namespace="main").get(first.key) == first
    first.value["zero"] = 99
    assert store.get(first.key).value["zero"] == 0
    with pytest.raises(PluginStorageConflict):
        store.put(first.key, "wrong", expected_revision=0)
    changed = store.put(first.key, [0, False, None], expected_revision=first.revision)
    assert changed.revision > first.revision
    assert store.delete(first.key, expected_revision=changed.revision)
    assert not store.delete(first.key)
    rebuilt = store.put(first.key, "rebuilt", expected_revision=0)
    with pytest.raises(PluginStorageConflict):
        store.delete(first.key, expected_revision=changed.revision)
    assert rebuilt.revision > changed.revision
    assert [row.key for row in store.scan(prefix="key\x00")] == [first.key]
    assert factory("other", namespace="main").get(first.key) is None
    assert factory("portable", namespace="other").get(first.key) is None
    for key in ("page/a", "page/b", "page/c"):
        store.put(key, key)
    page = store.scan(prefix="page/", limit=2)
    assert [row.key for row in page] == ["page/a", "page/b"]
    assert [row.key for row in store.scan(prefix="page/", after=page[-1].key, limit=2)] == ["page/c"]


def assert_invalid_values(store):
    for value in ({1: "integer object key"}, float("nan"), float("inf"), ("tuple",), object()):
        with pytest.raises(ValueError):
            store.put("invalid", value)
    for revision in (-1, True, 1.1, "1"):
        with pytest.raises(ValueError):
            store.put("invalid", "value", expected_revision=revision)
    for ttl in (0, -1, True, float("inf"), "1"):
        with pytest.raises(ValueError):
            store.put("invalid", "value", ttl_seconds=ttl)
    for limit in (0, 201, True):
        with pytest.raises(ValueError):
            store.scan(limit=limit)
    assert store.get("invalid") is None
