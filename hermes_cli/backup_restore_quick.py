"""Offline quick-snapshot restoration with explicit backend boundaries."""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hermes_cli.backup")


def restore_snapshot_exclusive(snapshot_id: str, home: Path) -> bool:
    """Restore state from a quick snapshot while ``home`` is reserved."""
    from gateway.runtime_ownership import exclusive_maintenance
    from hermes_cli.backup import quick_snapshot_dir, _is_trusted_root_auth_alias, _snapshot_epochs_restorable, _restore_snapshot_entry
    from hermes_cli.backup_database_policy import DatabaseBackupPolicy
    snap_dir = quick_snapshot_dir(snapshot_id, home)
    if snap_dir is None:
        return False
    with open(snap_dir / "manifest.json", encoding="utf-8-sig") as f:
        meta = json.load(f)
    source = meta.get("database_storage") or meta.get("session_storage") or {}
    source_backend = source.get("backend") if isinstance(source, dict) else None
    policy = DatabaseBackupPolicy(home, {".": source_backend} if source_backend in ("sqlite", "postgresql") else {})
    policy.validate_restore(meta.get("files", {}))

    snap_res, home_res = snap_dir.resolve(), home.resolve()

    def _entry_paths(rel: str) -> Optional[tuple[Path, Path]]:
        # Security: reject absolute paths and traversals in manifest entries
        src, dst = snap_dir / rel, home / rel
        if not src.resolve().is_relative_to(snap_res):
            return None
        if not dst.resolve().is_relative_to(home_res):
            # Named profiles may deliberately share the machine-root auth store via an
            # auth.json symlink. Let only that exact trusted alias reach _restore_auth_json;
            # every other manifest destination outside the profile remains a traversal.
            if rel != "auth.json" or not _is_trusted_root_auth_alias(dst, home):
                return None
        return src, dst

    homes = {home}
    for rel in meta.get("files", {}):
        entry = _entry_paths(rel)
        if entry and Path(rel).name == "config.yaml":
            policy.validate_config(rel, entry[0].read_bytes)
        if entry and policy.snapshot(entry[1]):
            homes.update([entry[1].absolute().parent, entry[1].resolve().parent])
    with exclusive_maintenance(homes):
        # Epoch safety is a whole-profile preflight: copying config first would
        # both partially roll back the profile and report a refused DB as success.
        if not _snapshot_epochs_restorable(meta.get("files", {}), _entry_paths):
            return False

        restored = 0
        auth_restore_failed = False
        for rel in meta.get("files", {}):
            entry = _entry_paths(rel)
            if entry is None:
                logger.error("Manifest path traversal blocked: %s", rel)
                if rel == "auth.json":
                    auth_restore_failed = True
                continue
            src, dst = entry
            if not policy.include(dst):
                continue
            if not src.exists():
                if rel == "auth.json":
                    logger.error("Snapshot auth.json listed in manifest is missing: %s", src)
                    auth_restore_failed = True
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            if _restore_snapshot_entry(rel, src, dst, sqlite_snapshot=policy.snapshot(dst)):
                restored += 1
            elif rel == "auth.json":
                auth_restore_failed = True

    logger.info("Restored %d files from snapshot %s", restored, snapshot_id)
    return restored > 0 and not auth_restore_failed
