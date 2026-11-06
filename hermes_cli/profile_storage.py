"""New profile identities are allocated before its staging directory is published."""

import uuid


def fork_storage_identity(home):
    from hermes_cli.config_backend import write_config_key
    from hermes_cli.config_effective import load_user_config_effective
    from hermes_cli.db_setup import _backend, _section
    from hermes_db.errors import StorageConfigurationError
    from hermes_db.file_scope import owner_id
    config_path = home / "config.yaml"
    config = load_user_config_effective(config_path, fail_closed=True)
    session = _section(_section(config, "storage"), "session")
    backend = _backend(session)
    pg = _section(session, "postgresql")
    if backend == "postgresql" or pg.get("store_id"):
        fresh = uuid.uuid4().hex
        write_config_key(config_path, "storage.session.postgresql.store_id", fresh)
        saved = load_user_config_effective(config_path, fail_closed=True)
        selected = _section(_section(_section(saved, "storage"), "session"), "postgresql")
        if selected.get("store_id") != fresh:
            raise StorageConfigurationError("Managed configuration must allow a distinct PostgreSQL store_id for each new profile")
    file_id = home / ".file-store-id"
    if file_id.exists() or file_id.is_symlink():
        file_id.unlink()
        if owner_id(home, create=True) is None:
            raise OSError("Cannot allocate the new profile's file owner identity")
