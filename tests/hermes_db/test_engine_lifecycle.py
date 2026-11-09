"""Real SQLAlchemy pool construction without opening a database connection."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import Mock

import pytest

from hermes_db.backends.postgresql import engine
from hermes_db.errors import StorageConfigurationError, StorageUnavailableError
from hermes_db.settings import PostgresSettings

sqlalchemy = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")


@pytest.fixture(autouse=True)
def clean_pools():
    engine.close_engines()
    yield
    engine.close_engines()


def test_concurrent_acquisition_reuses_pool_across_schemas():
    settings = PostgresSettings("postgresql://u:opaque@localhost/db", "schema_one")
    barrier = Barrier(4)

    def acquire(index):
        barrier.wait(timeout=10)
        return engine.get_engine(replace(settings, schema=f"schema_{index}"))

    with ThreadPoolExecutor(max_workers=4) as workers:
        pools = list(workers.map(acquire, range(4)))
    assert all(pool is pools[0] for pool in pools)
    assert engine.get_engine(replace(settings, dsn="postgresql+psycopg://u:opaque@localhost/db")) is pools[0]
    assert engine.close_engines() == 1
    assert engine.close_engines() == 0
    assert engine.get_engine(settings) is not pools[0]


def test_pool_target_credentials_and_budget_settings_are_not_conflated():
    settings = PostgresSettings("postgresql://u:opaque@localhost/db", "hermes")
    first = engine.get_engine(settings)
    assert engine.get_engine(replace(settings, dsn="postgresql://u:rotated@localhost/db")) is not first
    assert engine.get_engine(replace(settings, pool_size=2)) is not first
    assert "opaque" not in repr(settings)
    assert all("opaque" not in repr(key) for key in engine._pools)


def test_connect_error_is_redacted_and_never_falls_back(monkeypatch):
    settings = PostgresSettings("postgresql://u:opaque@localhost/db", "hermes")
    pool = Mock()
    pool.connect.side_effect = sqlalchemy.exc.OperationalError("private SQL", {}, Exception(settings.dsn))
    monkeypatch.setattr(engine, "get_engine", lambda _: pool)
    with pytest.raises(StorageUnavailableError) as error:
        with engine.read_connection(settings):
            pytest.fail("connection must not be yielded")
    assert "opaque" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("options", [
    {"pool_size": 0}, {"max_overflow": -1}, {"pool_timeout_seconds": float("inf")},
    {"pool_size": True}, {"connect_timeout_seconds": 0}, {"connection_budget": 2},
    {"schema": "pg_catalog"}, {"schema": "unsafe; DROP SCHEMA public"},
])
def test_invalid_pool_and_schema_settings_fail_before_connection(options):
    defaults = {"dsn": "postgresql://localhost/unused", "schema": "hermes"}
    with pytest.raises(StorageConfigurationError):
        PostgresSettings(**(defaults | options))


@pytest.mark.parametrize("dsn", ["not a URL with private:password", "sqlite:///local.db",
                                   "postgresql+asyncpg://localhost/db"])
def test_wrong_or_malformed_driver_url_is_rejected_without_echo(dsn):
    with pytest.raises(StorageConfigurationError) as error:
        engine.get_engine(PostgresSettings(dsn, "hermes"))
    assert "password" not in str(error.value)
