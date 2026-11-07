"""File snapshots describe external database exclusions without managing that service."""


def snapshot_storage(home, files=()):
    from hermes_cli.db_setup import storage_backend
    backend = storage_backend(home)
    if backend == "postgresql":
        print("PostgreSQL session data is excluded from this file backup; database backup and restore are operator-managed.")
    return {"backend": backend, "included": backend == "sqlite" and "state.db" in files}


def full_backup_notice(root):
    from pathlib import Path
    from hermes_constants import named_profile_has_identity
    from hermes_cli.db_setup import storage_backend
    homes = [Path(root)]
    profiles = Path(root) / "profiles"
    if profiles.is_dir():
        homes.extend(path for path in profiles.iterdir() if path.is_dir() and named_profile_has_identity(path))
    if any(storage_backend(home) == "postgresql" for home in homes):
        print("PostgreSQL session data is excluded from this file backup; database backup and restore are operator-managed.")


def run_quick_backup(args):
    """CLI entry point for a local-file state snapshot."""
    from hermes_cli.backup import create_quick_snapshot, list_quick_snapshots
    from hermes_constants import display_hermes_home
    snap_id = create_quick_snapshot(label=getattr(args, "label", None))
    if snap_id:
        print(f"State snapshot created: {snap_id}")
        snaps = list_quick_snapshots()
        print(f"  {len(snaps)} snapshot(s) stored in {display_hermes_home()}/state-snapshots/")
        print(f"  Restore with: /snapshot restore {snap_id}")
    else:
        print("No state files found to snapshot.")
