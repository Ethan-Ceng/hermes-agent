"""Process-owned PostgreSQL pools; no connection is held by a storage handle."""

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from threading import RLock

from hermes_db.errors import StorageConfigurationError, StorageDriverError, StorageUnavailableError
from hermes_db.settings import PostgresSettings


@dataclass(frozen=True)
class _PoolKey:
    pid: int
    dsn: str = field(repr=False)
    pool_size: int
    max_overflow: int
    pool_timeout_seconds: float
    connect_timeout_seconds: int


_pools: dict = {}
_lock = RLock()


def require_postgresql_driver():
    try:
        import sqlalchemy
        import psycopg
        import alembic
    except ImportError:
        raise StorageDriverError("PostgreSQL drivers unavailable; install the postgresql extra through Hermes PM") from None
    return sqlalchemy, psycopg, alembic


def _connection_url(dsn):
    sqlalchemy, _, _ = require_postgresql_driver()
    try:
        url = sqlalchemy.engine.make_url(dsn)
    except (ValueError, sqlalchemy.exc.ArgumentError):
        raise StorageConfigurationError("PostgreSQL DSN is not a valid connection URL") from None
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise StorageConfigurationError("PostgreSQL DSN must use the synchronous psycopg driver")
    return url.set(drivername="postgresql+psycopg")


def get_engine(settings: PostgresSettings):
    sqlalchemy, _, _ = require_postgresql_driver()
    url = _connection_url(settings.dsn)
    key = _PoolKey(os.getpid(), url.render_as_string(hide_password=False), settings.pool_size,
                   settings.max_overflow, settings.pool_timeout_seconds, settings.connect_timeout_seconds)
    with _lock:
        engine = _pools.get(key)
        if engine is None:
            engine = sqlalchemy.create_engine(
                url, pool_size=settings.pool_size, max_overflow=settings.max_overflow,
                pool_timeout=settings.pool_timeout_seconds, pool_pre_ping=True,
                hide_parameters=True, connect_args={"connect_timeout": settings.connect_timeout_seconds},
            )
            _pools[key] = engine
        return engine


@contextmanager
def read_connection(settings: PostgresSettings):
    sqlalchemy, _, _ = require_postgresql_driver()
    try:
        conn = get_engine(settings).connect()
    except (sqlalchemy.exc.DBAPIError, sqlalchemy.exc.TimeoutError):
        raise StorageUnavailableError("PostgreSQL connection unavailable or pool wait timed out") from None
    try:
        with conn:
            conn.execute(sqlalchemy.text("SELECT set_config('lock_timeout', :lock_timeout, true), "
                                         "set_config('statement_timeout', :statement_timeout, true)"),
                         {"lock_timeout": str(max(1, int(settings.write_lock_timeout_seconds * 1000))),
                          "statement_timeout": str(max(1, int(settings.statement_timeout_seconds * 1000)))})
            yield conn
    except sqlalchemy.exc.DBAPIError:
        raise StorageUnavailableError("PostgreSQL read failed") from None


def close_engines() -> int:
    """Application shutdown calls this after consumers finish; safe to repeat."""
    pid = os.getpid()
    with _lock:
        keys = [key for key in _pools if key.pid == pid]
        engines = [_pools.pop(key) for key in keys]
    for engine in engines:
        engine.dispose()
    return len(engines)
