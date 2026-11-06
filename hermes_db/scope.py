"""Server-resolved identities, independent of any database driver."""

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import re

from hermes_db.errors import StorageConfigurationError


@dataclass(frozen=True)
class DatabaseScope:
    profile_home: Path
    store_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "profile_home", Path(self.profile_home).resolve())
        if self.store_id is not None and (
            not isinstance(self.store_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.store_id)
        ):
            raise StorageConfigurationError("storage.session.postgresql.store_id must be a stable identifier")

    def require_store_id(self) -> str:
        if self.store_id is None:
            raise StorageConfigurationError("storage.session.postgresql.store_id is required")
        return self.store_id


@contextmanager
def bind_profile_home(scope: DatabaseScope):
    """Bind deferred SQLite configuration reads without changing process env."""
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(scope.profile_home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)
