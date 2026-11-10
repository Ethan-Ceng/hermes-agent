"""Domain resources on an owned random schema; all business rows are scoped."""

from dataclasses import replace
import json

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def settings(postgres_test_config, postgres_schema):
    return replace(postgres_test_config.settings, schema=postgres_schema)


def test_domain_resource_persistence_isolation_pool_and_lifetime(settings, tmp_path):
    from sqlalchemy import select
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageClosedError
    from hermes_db.factory import acquire_domain
    from hermes_db.schema import upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings
    from hermes_db.tables.conversations import system_prompts
    from hermes_db.core.values import decode_text, encode_text

    upgrade_schema(settings)
    config = DatabaseSettings("postgresql", settings)
    scope = DatabaseScope(tmp_path, "one")
    resource = acquire_domain("sessions", config, scope, sqlite_path=tmp_path / "cron/unused.db")
    peer = acquire_domain("sessions", config, DatabaseScope(tmp_path / "peer", "two"))
    pool = get_engine(settings)
    assert resource.sqlite_path is None
    value = "中文🙂\x00exact"
    document = {"nul": value, "types": [False, 0, "0", None, {}, []], "time": "2026-11-07T18:30:00+08:00"}
    for store, payload in ((resource, value), (peer, json.dumps(document))):
        with store.write() as conn:
            conn.execute(system_prompts.insert(), {"store_id": store.scope.store_id, "hash": "same",
                                                   "prompt": encode_text(payload)})
        assert pool.pool.checkedout() == 0
    resource.close()
    with pytest.raises(StorageClosedError), resource.read():
        pytest.fail("resource was released")
    with acquire_domain("sessions", config, scope) as reopened:
        for store, expected in ((reopened, value), (peer, json.dumps(document))):
            with store.read() as conn:
                saved = conn.scalar(select(system_prompts.c.prompt).where(
                    system_prompts.c.store_id == store.scope.store_id, system_prompts.c.hash == "same"))
                assert decode_text(saved) == expected
    peer.close()
    assert pool is get_engine(settings)
    assert pool.pool.checkedout() == 0
    assert not (tmp_path / "cron/unused.db").exists()


def test_missing_domains_never_initialize_at_open_and_all_capabilities_require_tables(settings, tmp_path):
    from sqlalchemy import inspect, text
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageSchemaError
    from hermes_db.factory import acquire_domain
    from hermes_db.schema import schema_status, upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings

    config, scope = DatabaseSettings("postgresql", settings), DatabaseScope(tmp_path, "one")
    with pytest.raises(StorageSchemaError, match="sessions.*not initialized"):
        acquire_domain("sessions", config, scope)
    assert not inspect(get_engine(settings)).get_table_names(schema=settings.schema)
    status = upgrade_schema(settings)
    assert status == upgrade_schema(settings)
    assert status["domains"]["sessions"]["ready"]
    assert status["full_system_ready"]
    assert all(domain["ready"] and domain["supported"] for domain in status["domains"].values())
    with acquire_domain("matrix_crypto", config, scope) as resource:
        assert resource.scope == scope
    from hermes_db.tables.matrix_crypto import olm_sessions
    with get_engine(settings).begin() as conn:
        quoted = conn.dialect.identifier_preparer.quote(settings.schema)
        conn.execute(text(f"DROP TABLE {quoted}.{olm_sessions.name} CASCADE"))
    status = schema_status(settings)
    assert not status["full_system_ready"]
    assert olm_sessions.name in status["domains"]["matrix_crypto"]["missing_tables"]
    with pytest.raises(StorageSchemaError):
        acquire_domain("matrix_crypto", config, scope)
    assert olm_sessions.name not in inspect(get_engine(settings)).get_table_names(schema=settings.schema)
    with get_engine(settings).begin() as conn:
        quoted = conn.dialect.identifier_preparer.quote(settings.schema)
        conn.execute(text(f"DROP TABLE {quoted}.system_prompts CASCADE"))
    status = schema_status(settings)
    assert not status["ready"]
    assert "system_prompts" in status["domains"]["sessions"]["missing_tables"]
    with pytest.raises(StorageSchemaError):
        acquire_domain("sessions", config, scope)


def test_previous_revision_forward_upgrade(settings):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.schema import schema_status, upgrade_schema

    config = Config()
    config.set_main_option("script_location", str(Path("hermes_db/migrations").resolve()))
    config.attributes["schema"] = settings.schema
    with get_engine(settings).begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0003_archive_refs")
    assert not schema_status(settings)["domains"]["sessions"]["ready"]
    assert upgrade_schema(settings)["domains"]["sessions"]["ready"]


def test_permission_failure_propagates_and_returns_connection(settings, tmp_path):
    from sqlalchemy import select, text
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageUnavailableError
    from hermes_db.factory import acquire_domain
    from hermes_db.schema import upgrade_schema
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings
    from hermes_db.tables.conversations import system_prompts

    upgrade_schema(settings)
    pool = get_engine(settings)
    with acquire_domain("sessions", DatabaseSettings("postgresql", settings), DatabaseScope(tmp_path, "one")) as resource:
        quoted = pool.dialect.identifier_preparer.quote(settings.schema)
        with pool.begin() as conn:
            superuser = conn.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
            conn.execute(text(f"REVOKE SELECT ON {quoted}.system_prompts FROM CURRENT_USER"))
        try:
            with pytest.raises(StorageUnavailableError), resource.read() as conn:
                if superuser:
                    # Transaction-local builtin role; no accounts or global grants are changed.
                    conn.execute(text("SET LOCAL ROLE pg_monitor"))
                conn.execute(select(system_prompts).where(system_prompts.c.store_id == resource.scope.store_id))
            assert pool.pool.checkedout() == 0
        finally:
            with pool.begin() as conn:
                conn.execute(text(f"GRANT SELECT ON {quoted}.system_prompts TO CURRENT_USER"))
