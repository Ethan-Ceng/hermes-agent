"""Server-resolved identities, independent of any database driver."""

from dataclasses import dataclass
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
            raise StorageConfigurationError("storage.postgresql.store_id must be a stable identifier")

    def require_store_id(self) -> str:
        if self.store_id is None:
            raise StorageConfigurationError("storage.postgresql.store_id is required")
        return self.store_id
