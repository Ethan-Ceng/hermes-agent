"""Resolved storage settings; no environment or profile reads."""

from dataclasses import dataclass, field
import math
import re

from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class PostgresSettings:
    dsn: str = field(repr=False)
    schema: str
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout_seconds: float = 30
    connect_timeout_seconds: int = 10
    connection_budget: int = 10
    write_lock_timeout_seconds: float = 10
    statement_timeout_seconds: float = 60

    def __post_init__(self):
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise StorageConfigurationError("PostgreSQL DSN secret is missing")
        if not isinstance(self.schema, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.schema):
            raise StorageConfigurationError("PostgreSQL schema must be an explicit lowercase identifier")
        if self.schema.startswith("pg_") or self.schema == "information_schema":
            raise StorageConfigurationError("PostgreSQL system schemas cannot hold Profile storage")
        for name, minimum in (("pool_size", 1), ("max_overflow", 0),
                              ("connect_timeout_seconds", 1), ("connection_budget", 1)):
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise StorageConfigurationError(f"PostgreSQL {name} must be an integer >= {minimum}")
        for name in ("pool_timeout_seconds", "write_lock_timeout_seconds", "statement_timeout_seconds"):
            _positive_seconds(name, getattr(self, name))
        if self.pool_size + self.max_overflow > self.connection_budget:
            raise StorageConfigurationError("PostgreSQL pool maximum exceeds its process connection_budget")


def _positive_seconds(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise StorageConfigurationError(f"PostgreSQL {name} must be finite and positive")


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str = "sqlite"
    postgresql: PostgresSettings | None = None

    def __post_init__(self):
        if self.backend not in ("sqlite", "postgresql"):
            raise StorageConfigurationError("storage.backend must be sqlite or postgresql")
        if self.backend == "postgresql" and self.postgresql is None:
            raise StorageConfigurationError("PostgreSQL settings are required")
