"""Resume a local Profile directory move against its captured PG dataset, without copying data."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager

from hermes_db.errors import StorageConfigurationError


def _locations(old, new):
    old, new = Path(old), Path(new)
    if old.parent.resolve() != new.parent.resolve():
        raise StorageConfigurationError("Profile move must remain within its owning profiles directory")
    parent = old.parent.resolve()
    old, new = parent / old.name, parent / new.name
    name = hashlib.sha256(json.dumps([str(old), str(new)]).encode()).hexdigest()
    return old, new, parent / ".home-moves" / f"{name}.json"


def pending_move(old, new):
    old, new, journal = _locations(old, new)
    return not old.exists() and new.is_dir() and journal.is_file()


def resolve_move(old_name, new_name):
    from hermes_cli import profiles
    old, new = profiles.get_profile_dir(old_name), profiles.get_profile_dir(new_name)
    resuming = pending_move(old, new)
    if not old.is_dir() and not resuming:
        raise profiles._unknown_profile_error(old_name)
    if new.exists() and not resuming:
        raise profiles._profile_exists_error(new_name)
    return old, new


def _identity(resource):
    from hermes_db.core.values import resource_key
    return dict(store_id=resource.scope.require_store_id(), target=resource_key(resource._transactions))


def _capture(home):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    with _owning_profile(home), acquire_profile_domain("kanban_tasks", profile_home=home) as resource:
        return _identity(resource)


def _write_journal(path, value):
    from hermes_dir_acl import make_user_dir
    from utils import atomic_json_write
    make_user_dir(path.parent, mode=0o700, parents=True, exist_ok=True)
    if path.parent.resolve() != path.parent or path.is_symlink():
        raise StorageConfigurationError("Profile move journal is redirected")
    atomic_json_write(path, value, mode=0o600, fsync_dir=True)


@contextmanager
def _gate(journal):
    from hermes_dir_acl import make_user_dir
    from pm.filesystem import lock_path, unlock_fd
    from hermes_db.errors import StorageBusyError
    make_user_dir(journal.parent, mode=0o700, parents=True, exist_ok=True)
    if journal.parent.resolve() != journal.parent:
        raise StorageConfigurationError("Profile move lock directory is redirected")
    descriptor = lock_path(journal.with_suffix(".lock"), timeout=10, create_dir=False)
    if descriptor is None:
        raise StorageBusyError("Profile directory move is already in progress")
    try:
        yield
    finally:
        unlock_fd(descriptor)
        os.close(descriptor)


def _reanchor_database(old, new, identity):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.integration.profile_paths import reanchor
    with _owning_profile(new), acquire_profile_domain("kanban_tasks", profile_home=new) as resource:
        if resource.settings.backend != "postgresql" or _identity(resource) != identity:
            raise StorageConfigurationError("Profile move database identity changed; preserve the journal and local files")
        reanchor(resource, old, new)


def _markers(old, new, identity):
    from hermes_db.integration.profile_paths import payload_paths
    patterns = ("kanban/data/*/attachments/*/*/.owner.json", "kanban/imports/*/.owner.json", "kanban/uploads/*/*/manifest.json")
    for pattern in patterns:
        for path in new.glob(pattern):
            if path.resolve() != path or path.is_symlink():
                raise StorageConfigurationError("Profile content marker is redirected")
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            owner = document.get("owner") if "owner" in document else document
            target = document.get("board_target", document.get("target"))
            if owner.get("store_id") != identity["store_id"] or target != identity["target"]:
                continue
            changed = payload_paths(document, old, new)
            if "home" in document:
                changed["home"] = str(new)
            if changed != document:
                _replace_marker(path, changed)


def _replace_marker(path, document):
    from utils import fsync_directory
    # This maintenance owner rewrites an existing private file while its Profile
    # is deliberately unpublished. Never mkdir or relax the ordinary tombstone guard.
    descriptor, name = tempfile.mkstemp(prefix=".profile-move-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps(document, ensure_ascii=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def move_directory(old, new):
    from hermes_cli.db_setup import storage_backend
    old, new, journal = _locations(old, new)
    if not journal.is_file() and storage_backend(old) == "sqlite":
        old.rename(new)
        return
    with _gate(journal):
        _move_captured(old, new, journal)


def _move_captured(old, new, journal):
    from hermes_constants import mark_named_profile_deleted, clear_named_profile_deleted
    from utils import fsync_directory
    if any(path.resolve() != path for path in (old, new)):
        raise StorageConfigurationError("PG Profile move must use canonical directory entries")
    if journal.is_file():
        value = json.loads(journal.read_text(encoding="utf-8-sig"))
        if value.get("version") != 1 or value.get("old") != str(old) or value.get("new") != str(new):
            raise StorageConfigurationError("Profile move journal does not match these directories")
        identity = {key: value[key] for key in ("store_id", "target")}
    else:
        identity = _capture(old)
        _write_journal(journal, dict(version=1, old=str(old), new=str(new), **identity))
    mark_named_profile_deleted(new)
    try:
        if old.exists():
            if new.exists() or _capture(old) != identity:
                raise StorageConfigurationError("Profile move source or destination changed; preserve the journal")
            old.rename(new)
            fsync_directory(new.parent)
        if not new.is_dir():
            raise StorageConfigurationError("Profile move destination is missing; preserve the journal")
        _reanchor_database(old, new, identity)
        _markers(old, new, identity)
        clear_named_profile_deleted(new)
        journal.unlink()
    except Exception:
        if old.is_dir() and not new.exists():
            clear_named_profile_deleted(new)
        raise
