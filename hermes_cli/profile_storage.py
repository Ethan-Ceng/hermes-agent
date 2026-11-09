"""New profile identities are allocated before its staging directory is published."""

import uuid


def fork_storage_identity(home):
    from hermes_cli.config_backend import supports_file_tooling, write_config_key
    # Non-file backends refuse cloning and own the final Profile's configuration themselves.
    if not supports_file_tooling():
        return
    from hermes_cli.config_effective import load_user_config_effective
    from hermes_cli.db_setup import _backend, _section, _storage
    from hermes_db.errors import StorageConfigurationError
    from hermes_db.core.file_scope import owner_id
    config_path = home / "config.yaml"
    config = load_user_config_effective(config_path, fail_closed=True)
    storage = _storage(config)
    backend = _backend(storage)
    pg = _section(storage, "postgresql")
    if backend == "postgresql" or pg.get("store_id"):
        fresh = uuid.uuid4().hex
        write_config_key(config_path, "storage.postgresql.store_id", fresh)
        saved = load_user_config_effective(config_path, fail_closed=True)
        selected = _section(_storage(saved), "postgresql")
        if selected.get("store_id") != fresh:
            raise StorageConfigurationError("Managed configuration must allow a distinct PostgreSQL store_id for each new profile")
    file_id = home / ".file-store-id"
    if file_id.exists() or file_id.is_symlink():
        file_id.unlink()
        if owner_id(home, create=True) is None:
            raise OSError("Cannot allocate the new profile's file owner identity")
