"""Compose storage from the owning Profile's effective config and secret scope."""

from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
import re

from hermes_db.errors import StorageConfigurationError
from hermes_db.scope import DatabaseScope
from hermes_db.settings import DatabaseSettings, PostgresSettings


@contextmanager
def _owning_profile(home):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from agent.secret_scope import (
        build_profile_secret_scope, current_secret_scope_home, reset_secret_scope, set_secret_scope,
    )

    home_token = set_hermes_home_override(home)
    secret_token = None
    try:
        bound = current_secret_scope_home()
        if bound is None or Path(bound).resolve() != home:
            secret_token = set_secret_scope(build_profile_secret_scope(home), profile_home=str(home))
        yield
    finally:
        if secret_token is not None:
            reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)


def _section(config, name):
    value = config.get(name, {})
    if not isinstance(value, Mapping):
        raise StorageConfigurationError(f"Storage configuration section {name} must be a mapping")
    return value


def _resolve_settings(config, home):
    from agent.secret_scope import get_secret

    session = _section(_section(config, "storage"), "session")
    backend = session.get("backend", "sqlite")
    if backend == "sqlite":
        return DatabaseSettings(), DatabaseScope(home)
    if backend != "postgresql":
        raise StorageConfigurationError("storage.session.backend must be sqlite or postgresql")
    pg = _section(session, "postgresql")
    scope = DatabaseScope(home, pg.get("store_id"))
    scope.require_store_id()
    env_name = pg.get("dsn_env", "HERMES_POSTGRES_DSN")
    if not isinstance(env_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise StorageConfigurationError("PostgreSQL dsn_env must name a profile secret")
    if "dsn" in pg:
        raise StorageConfigurationError("PostgreSQL DSNs belong in profile secrets; configure dsn_env")
    options = {key: pg[key] for key in (
        "pool_size", "max_overflow", "pool_timeout_seconds", "connect_timeout_seconds", "connection_budget",
    ) if key in pg}
    settings = PostgresSettings(dsn=get_secret(env_name) or "", schema=pg.get("schema", ""), **options)
    return DatabaseSettings(backend, settings), scope


def resolve_db_configuration(profile_home: Path | None = None):
    from hermes_constants import get_hermes_home
    from hermes_cli.config_effective import load_user_config_effective

    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    with _owning_profile(home):
        config = load_user_config_effective(home / "config.yaml", fail_closed=True)
        return _resolve_settings(config, home)


def open_profile_db(profile_home: Path | None = None):
    """Storage composition entry used by the ordinary surfaces in Task 17."""
    from hermes_db.factory import acquire_db

    settings, scope = resolve_db_configuration(profile_home)
    with _owning_profile(scope.profile_home):
        return acquire_db(settings, scope)
