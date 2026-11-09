"""Backend-aware identity for process-owned Kanban consumers; never a fake PG file."""


def board_storage_identity(kb, slug, *, db_path=None):
    from hermes_cli.db_setup import storage_backend
    if storage_backend() == "postgresql":
        from hermes_db.factory import acquire_profile_domain
        from hermes_db.domains.kanban.postgres.catalog import _lookup
        with acquire_profile_domain("kanban_tasks") as resource:
            with resource.read() as conn:
                row = _lookup(conn, resource, slug)
            return ("postgresql", resource.scope.require_store_id(), row["board_id"] if row else slug)
    path = db_path if db_path is not None else kb.kanban_db_path(slug)
    from pathlib import Path
    path = Path(path).expanduser()
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    try:
        stat = path.stat()
    except OSError:
        return (resolved, None, None)
    return (resolved, stat.st_mtime_ns, stat.st_size)
