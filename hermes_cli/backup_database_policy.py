"""File-backup boundaries for Profile-owned databases; PG data is operator-managed."""

import json
from pathlib import Path

from hermes_db.errors import StorageConfigurationError

ROOT_DATABASES = frozenset({"state.db", "shared-state.db", "projects.db", "verification_evidence.db", "kanban.db",
    "response_store.db", "memory_store.db", "retaindb_queue.db", "metrics.sqlite3"})
DATABASE_PATHS = frozenset({"cron/executions.db", "cron/deliveries.db", "cron/notepad.db",
    "gateway/discord_message_recovery.db", "platforms/matrix/store/crypto.db", "matrix/store/crypto.db",
    "telemetry/shared_metrics/metrics.sqlite3"})
DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
SIDECARS = ("-wal", "-shm", "-journal")


def system_database(relative):
    value = Path(relative).as_posix()
    for suffix in SIDECARS:
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    path = Path(value)
    if value in ROOT_DATABASES or value in DATABASE_PATHS:
        return True
    if path.suffix not in DATABASE_SUFFIXES:
        return False
    parts = path.parts
    return (len(parts) >= 3 and parts[0] == "plugin-data") or (
        len(parts) >= 3 and parts[:2] == ("kanban", "boards") and path.name == "kanban.db")


def archive_profiles(comment):
    if not comment:
        return {}
    try:
        document = json.loads(comment)
    except (ValueError, UnicodeError):
        return {}  # Non-Hermes ZIP comments are ordinary legacy archives.
    if not isinstance(document, dict) or "hermes_database_storage" not in document:
        return {}
    document = document["hermes_database_storage"]
    profiles = document.get("profiles") if isinstance(document, dict) else None
    if not isinstance(profiles, dict) or document.get("version") != 1:
        raise StorageConfigurationError("Unsupported database-storage backup metadata")
    for key, backend in profiles.items():
        path = Path(key)
        if backend not in ("sqlite", "postgresql") or not (key == "." or (
                len(path.parts) == 2 and path.parts[0] == "profiles" and path.parts[1] not in (".", ".."))):
            raise StorageConfigurationError("Invalid database-storage backup scope")
    return profiles


class DatabaseBackupPolicy:
    def __init__(self, root, source_profiles=None):
        from hermes_constants import named_profile_has_identity
        from hermes_cli.db_setup import storage_backend
        self.root = Path(root).absolute()
        homes = [self.root]
        directory = self.root / "profiles"
        if directory.is_dir():
            homes.extend(path for path in directory.iterdir() if path.is_dir() and named_profile_has_identity(path))
        self.backends = {home.relative_to(self.root).as_posix(): storage_backend(home) for home in homes}
        self.source = source_profiles or {}
        selected = {**self.source, **self.backends}
        self.shared_owner = next((key for key in sorted(selected) if key.startswith("profiles/")
            and selected[key] == "sqlite"), None) if selected["."] == "postgresql" else None
        self.excluded = []

    def _owner(self, relative):
        path = Path(relative)
        parts = path.parts
        shared = path.name == "shared-state.db" or any(path.name == "shared-state.db" + suffix for suffix in SIDECARS)
        if len(parts) == 1 and shared and self.shared_owner is not None:
            return self.shared_owner, path
        if len(parts) >= 3 and parts[0] == "profiles":
            key = Path(*parts[:2]).as_posix()
            return key, Path(*parts[2:])
        return ".", path

    def _relative(self, path):
        try:
            return Path(path).absolute().relative_to(self.root)
        except ValueError:
            return None

    def _backend(self, owner):
        return self.backends.get(owner, self.source.get(owner, self.backends["."]))

    def include(self, path):
        relative = self._relative(path)
        if relative is None:
            return True
        owner, local = self._owner(relative)
        if not system_database(local):
            return True
        if self._backend(owner) == "postgresql" or str(local).endswith(SIDECARS):
            self.excluded.append(relative.as_posix())
            return False
        return True

    def snapshot(self, path):
        relative = self._relative(path)
        owner, local = self._owner(relative) if relative is not None else (".", Path(path))
        if self._backend(owner) == "postgresql" or self.source.get(owner) == "postgresql":
            return False
        return Path(path).suffix == ".db" or system_database(local)

    def describe(self, files=()):
        backend = self.backends["."]
        included = [str(relative) for relative in files if system_database(relative)]
        return {"backend": backend, "included": bool(included) if backend == "sqlite" else False,
            "included_files": included, "excluded_files": sorted(set(self.excluded)), "scope": "profile-owned databases"}

    def zip_comment(self):
        value = json.dumps({"hermes_database_storage": {"version": 1, "profiles": self.backends}}, separators=(",", ":")).encode()
        if len(value) > 65535:
            raise StorageConfigurationError("Database backup Profile metadata exceeds ZIP comment capacity")
        return value

    def validate_restore(self, relatives):
        for relative in relatives:
            owner, local = self._owner(relative)
            source = self.source.get(owner)
            target = self._backend(owner)
            if system_database(local) and (source == "postgresql" or target == "postgresql"):
                raise StorageConfigurationError("PostgreSQL file restore cannot import owned SQLite database data; database restore is operator-managed")
            if local == Path("config.yaml") and target == "postgresql" and source != "postgresql":
                raise StorageConfigurationError("File restore cannot prove the PostgreSQL backend scope; restore database configuration explicitly")

    def validate_config(self, relative, read_payload):
        owner, local = self._owner(relative)
        if local != Path("config.yaml") or "postgresql" not in (self.source.get(owner), self._backend(owner)):
            return
        from hermes_yaml import YAMLError
        from hermes_cli.config_backend import parse_config_document
        from hermes_cli.db_setup import _storage, _backend
        try:
            config = parse_config_document(read_payload())
        except (OSError, YAMLError, UnicodeError):
            raise StorageConfigurationError("Cannot verify backup database backend configuration") from None
        if not isinstance(config, dict):
            raise StorageConfigurationError("Cannot verify backup database backend configuration")
        backend = _backend(_storage(config))
        if backend != "postgresql":
            raise StorageConfigurationError("Backup database backend metadata contradicts config.yaml; preserve the selected Profile")


def policy_for_archive(root, archive, members, prefix):
    policy = DatabaseBackupPolicy(root, archive_profiles(archive.comment))
    relatives = [member[len(prefix):] if prefix and member.startswith(prefix) else member for member in members]
    policy.validate_restore(relative for relative in relatives if not relative.startswith("_external/"))
    for member, relative in zip(members, relatives):
        if not member.endswith("/") and Path(relative).name == "config.yaml":
            policy.validate_config(relative, lambda: archive.read(member))
    return policy
