"""Owner-lifetime maintenance for the selected Profile, independent of session retention gates."""

from pathlib import Path


def maintain_profile(profile_home=None):
    from hermes_constants import get_hermes_home
    from hermes_cli.db_setup import _owning_profile, storage_backend
    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    with _owning_profile(home):
        if storage_backend(home) == "sqlite":
            return {"backend": "sqlite"}
        from hermes_cli.db_domains import acquire_profile_domain
        from hermes_cli.kanban_storage_maintenance import replay_files, terminal_workspaces, pending_workspaces
        with acquire_profile_domain("kanban_tasks", profile_home=home) as resource:
            from hermes_cli.kanban_storage_effects import drain
            drain(resource)
            pending_workspaces(resource)
            from hermes_cli.kanban_storage_files import reconcile
            reconcile(resource)
            result = {"backend": "postgresql", "file_jobs": replay_files(resource), "workspaces": terminal_workspaces(resource)}
            from hermes_cli.kanban_storage_files import reclaim
            result["upload_chunks"] = reclaim(resource)
        _attachments(home)
        result["expired_plugin_records"] = _plugins(home)
        return result


def _plugins(home):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.maintenance import prune_plugin_records
    with acquire_profile_domain("plugins", profile_home=home) as resource, resource.write() as conn:
        return prune_plugin_records(conn, resource.scope)


def _attachments(home):
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.maintenance import attachment_namespace
    with acquire_profile_domain("room_attachments", profile_home=home) as resource, resource.read() as conn:
        namespace = attachment_namespace(conn, resource.scope)
    # Do not resurrect removed/custom content roots. Custom roots retain their
    # ordinary store-startup/prune owner; the default owner covers daemon files.
    if namespace is None or not (home / "hosted-room-attachments" / namespace).is_dir():
        return
    from gateway.hosted_room_attachments import HostedRoomAttachmentStore
    from gateway.hosted_room_storage import capture_room_store
    store = HostedRoomAttachmentStore(capture_room_store())
    store.reconcile_room_events()
    store.prune()
