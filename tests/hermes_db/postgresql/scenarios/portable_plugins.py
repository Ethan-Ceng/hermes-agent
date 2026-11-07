"""Actual child-process plugin races and restart reads, with every SQLite open refused."""

import sqlite3
import sys

attempts = []


def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("SQLite rejected in portable PG plugin process")


sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == "sqlite3.connect" else None)
from plugins.plugin_storage import plugin_store, PluginStorageConflict, PluginStorageQuotaError
from plugins.plugin_storage_types import MAX_VALUE_BYTES

role = sys.argv[1]
if role.startswith("cas-"):
    sys.stdin.readline()
    try:
        plugin_store("discord", namespace="race").put("same", role, expected_revision=0)
    except PluginStorageConflict:
        print("CAS_REFUSED")
    else:
        print("CAS_COMMITTED")
elif role.startswith("quota-"):
    sys.stdin.readline()
    try:
        plugin_store("discord", namespace="quota").put(role, "x" * (MAX_VALUE_BYTES - 2), expected_revision=0)
    except PluginStorageQuotaError:
        print("QUOTA_REFUSED")
    else:
        print("QUOTA_COMMITTED")
elif role == "read":
    row = plugin_store("discord", namespace="race").get("same")
    assert row.value in {"cas-a", "cas-b"} and row.revision > 0
    print("PG_PLUGIN_RESTART_READ_OK")
else:
    raise AssertionError("unknown portable plugin process role")
assert not attempts
