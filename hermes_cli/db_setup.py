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
    from hermes_cli.config_backend import ConfigBackendUnavailable
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
    except ConfigBackendUnavailable:
        raise StorageConfigurationError("Profile storage configuration is unavailable") from None
    finally:
        if secret_token is not None:
            reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)


def _section(config, name):
    value = config.get(name, {})
    if not isinstance(value, Mapping):
        raise StorageConfigurationError(f"Storage configuration section {name} must be a mapping")
    return value


def _storage(config):
    storage = _section(config, "storage")
    if "session" in storage:
        raise StorageConfigurationError(
            "storage.session is no longer supported; move backend to storage.backend "
            "and postgresql to storage.postgresql in config.yaml"
        )
    return storage


def _backend(storage):
    backend = storage.get("backend", "sqlite")
    if backend not in ("sqlite", "postgresql"):
        raise StorageConfigurationError("storage.backend must be sqlite or postgresql")
    return backend


def _resolve_settings(config, home):
    from agent.secret_scope import get_secret

    storage = _storage(config)
    backend = _backend(storage)
    if backend == "sqlite":
        return DatabaseSettings(), DatabaseScope(home)
    pg = _section(storage, "postgresql")
    scope = DatabaseScope(home, pg.get("store_id"))
    scope.require_store_id()
    env_name = pg.get("dsn_env", "HERMES_POSTGRES_DSN")
    if not isinstance(env_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise StorageConfigurationError("PostgreSQL dsn_env must name a profile secret")
    if "dsn" in pg:
        raise StorageConfigurationError("PostgreSQL DSNs belong in profile secrets; configure dsn_env")
    options = {key: pg[key] for key in (
        "pool_size", "max_overflow", "pool_timeout_seconds", "connect_timeout_seconds", "connection_budget",
        "write_lock_timeout_seconds", "statement_timeout_seconds",
    ) if key in pg}
    settings = PostgresSettings(dsn=get_secret(env_name) or "", schema=pg.get("schema", ""), **options)
    return DatabaseSettings(backend, settings), scope


def _storage_config(home):
    from hermes_cli.config_effective import load_user_config_effective
    from hermes_yaml import YAMLError
    try:
        return load_user_config_effective(home / "config.yaml", fail_closed=True)
    except (YAMLError, OSError):
        # Parser exceptions can include the offending config values. Expose only the owning path.
        raise StorageConfigurationError(
            f"Hermes stopped because your settings file ({home / 'config.yaml'}) could not be read; "
            "repair it before retrying storage operations"
        ) from None


def resolve_db_configuration(profile_home: Path | None = None):
    from hermes_constants import get_hermes_home

    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    with _owning_profile(home):
        config = _storage_config(home)
        return _resolve_settings(config, home)


def open_profile_db(profile_home: Path | None = None):
    """Storage composition entry used by the ordinary surfaces in Task 17."""
    from hermes_cli.db_sessions import _owner_only
    _owner_only()
    from hermes_cli.db_sessions import acquire_db

    settings, scope = resolve_db_configuration(profile_home)
    with _owning_profile(scope.profile_home):
        return acquire_db(settings, scope)


def storage_backend(profile_home: Path | None = None):
    """Driver/secret-free backend selection for file-tooling and cache boundaries."""
    from agent.safe_worker_policy import worker_config_snapshot
    from agent.runtime_session_store import current_worker_store, is_worker_process
    from hermes_constants import get_hermes_home
    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    if is_worker_process():
        from agent.runtime_domain_store import owner_binding
        binding = owner_binding(current_worker_store())
        if home != Path(binding['profile_home']).resolve():
            raise StorageConfigurationError('Worker storage belongs to its adopted Profile')
        return binding['backend']
    # The worker's effective loader already returns its frozen policy; don't hydrate Profile secrets first.
    if worker_config_snapshot() is not None:
        return _backend(_storage(_storage_config(home)))
    with _owning_profile(home):
        config = _storage_config(home)
        return _backend(_storage(config))


def open_profile_sessions(profile_home: Path | None = None, *, read_only=False):
    """Caller-owned resource; SQLite observational opens retain their no-DDL contract."""
    from hermes_cli.db_sessions import _owner_only
    _owner_only()
    from hermes_cli.db_sessions import acquire_db
    from hermes_db.domains.sessions.resource import SessionResource
    settings, scope = resolve_db_configuration(profile_home)
    if read_only and settings.backend == "sqlite":
        from hermes_state import SessionDB
        return SessionDB(db_path=scope.profile_home / "state.db", read_only=True)
    with _owning_profile(scope.profile_home):
        return SessionResource(acquire_db(settings, scope))
