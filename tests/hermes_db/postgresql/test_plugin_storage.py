"""Real PG plugin namespaces, durable CAS and explicit legacy SQLite refusal."""

import pytest
from hermes_db.errors import StorageConfigurationError

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_portable_plugin_scope_cas_reopen_and_aba(pg_profiles):
    from plugins.plugin_storage import plugin_store
    from plugins.plugin_storage_types import PluginStorageConflict
    with pg_profiles("one"):
        store = plugin_store("discord", namespace="recovery-cursors")
        first = store.put("channel\x00🙂", {"message": "零\x00", "false": False, "zero": 0, "null": None}, expected_revision=0)
        assert plugin_store("discord", namespace="recovery-cursors").get(first.key) == first
        with pytest.raises(PluginStorageConflict):
            store.put(first.key, {"wrong": True}, expected_revision=0)
        assert store.delete(first.key, expected_revision=first.revision)
        second = store.put(first.key, [0, False, None], expected_revision=0)
        assert second.revision > first.revision
        with pytest.raises(PluginStorageConflict):
            store.put(first.key, "stale", expected_revision=first.revision)
        assert plugin_store("other", namespace="recovery-cursors").get(first.key) is None
        assert plugin_store("discord", namespace="another").get(first.key) is None
    with pg_profiles("two"):
        assert plugin_store("discord", namespace="recovery-cursors").get(first.key) is None


def test_selected_pg_legacy_plugin_db_fails_before_sqlite_or_directory(pg_profiles):
    from plugins.plugin_storage import plugin_db
    with pg_profiles("one") as home:
        with pytest.raises(StorageConfigurationError, match="legacy-plugin.*plugin_store"):
            plugin_db("legacy-plugin")
        assert not (home / "plugin-data" / "legacy-plugin").exists()


def test_pg_public_portable_record_contract_and_validation(pg_profiles):
    from plugins.plugin_storage import plugin_store
    from tests.plugins.portable_storage_contracts import assert_invalid_values, assert_portable_records
    with pg_profiles("one"):
        assert_portable_records(plugin_store)
        assert_invalid_values(plugin_store("validation"))


def test_pg_expiry_prune_preserves_monotonic_revision(pg_profiles):
    from sqlalchemy import update
    from plugins.plugin_storage import plugin_store
    from hermes_db.domains.plugin_storage.records.api import open_plugin
    from hermes_db.domains.plugin_storage.records.postgres.operations.records import scope
    from hermes_db.tables.plugins import records
    with pg_profiles("one"):
        store = plugin_store("expiry")
        first = store.put("expired", "value", ttl_seconds=60)
        with open_plugin(store.reference, write=True) as conn:
            conn.execute(update(records).where(scope(records, store.reference), records.c.key == b"expired").values(expires_at=0))
        assert store.get("expired") is None
        assert store.prune_expired(limit=1) == 1
        assert store.put("expired", "new", expected_revision=0).revision > first.revision


def test_actual_discord_cursor_consumer_persists_and_isolates(pg_profiles):
    from gateway.config import PlatformConfig
    from plugins.platforms.discord.adapter import DiscordAdapter
    with pg_profiles("one"):
        adapter = DiscordAdapter(PlatformConfig(enabled=True, token="test-token"))
        adapter._advance_discord_recovery_cursor("channel", "message-1")
        assert DiscordAdapter(PlatformConfig(enabled=True, token="test-token"))._discord_recovery_cursor("channel") == "message-1"
        adapter._advance_discord_recovery_cursor("channel", "message-2")
        assert adapter._discord_recovery_cursor("channel") == "message-2"
    with pg_profiles("two"):
        assert DiscordAdapter(PlatformConfig(enabled=True, token="test-token"))._discord_recovery_cursor("channel") is None


def test_retained_key_quota_rolls_back_and_releases_after_delete(pg_profiles):
    from sqlalchemy import insert, update
    from plugins.plugin_storage import plugin_store, PluginStorageQuotaError
    from plugins.plugin_storage_types import MAX_NAMESPACE_KEYS
    from hermes_db.domains.plugin_storage.records.api import open_plugin
    from hermes_db.domains.plugin_storage.records.postgres.operations.records import scope
    from hermes_db.tables.plugins import namespaces, records
    with pg_profiles("one"):
        store = plugin_store("key-quota")
        first = store.put("original", 0)
        ref = store.reference
        # A retained dataset at the published bound; insertion through the public
        # API below must consult the actual database count, including earlier rows.
        with open_plugin(ref, write=True) as conn:
            conn.execute(insert(records), [dict(store_id=ref.store_id, plugin_id=ref.plugin_id, namespace=ref.namespace,
                key=f"key-{index:04d}".encode(), value=b"0", revision=index + 2) for index in range(MAX_NAMESPACE_KEYS - 1)])
            conn.execute(update(namespaces).where(scope(namespaces, ref)).values(revision=MAX_NAMESPACE_KEYS))
        with pytest.raises(PluginStorageQuotaError):
            store.put("overflow", False)
        assert store.get("overflow") is None
        assert store.get("original") == first
        assert store.delete("original", expected_revision=first.revision)
        assert store.put("overflow", False).revision == MAX_NAMESPACE_KEYS + 1


def test_unknown_plugin_commit_is_observable_without_blind_cas_retry(pg_profiles, monkeypatch):
    from contextlib import contextmanager
    from plugins.plugin_storage import plugin_store, PluginStorageConflict
    from hermes_db.domains.plugin_storage.records.postgres import store as implementation
    from hermes_db.errors import UnknownCommitError
    with pg_profiles("one"):
        store = plugin_store("unknown-commit")
        original = implementation.open_plugin
        @contextmanager
        def lose_ack(reference, *, write=False):
            with original(reference, write=write) as conn:
                yield conn
            if write:
                raise UnknownCommitError("injected confirmation loss after actual COMMIT")
        monkeypatch.setattr(implementation, "open_plugin", lose_ack)
        with pytest.raises(UnknownCommitError):
            store.put("request", {"accepted": True}, expected_revision=0)
        monkeypatch.setattr(implementation, "open_plugin", original)
        current = plugin_store("unknown-commit").get("request")
        assert current.value == {"accepted": True}
        with pytest.raises(PluginStorageConflict):
            store.put("request", {"accepted": True}, expected_revision=0)
        assert store.get("request") == current
