"""Driver-independent Matrix identity plus captured shared-PG target and namespace generation."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatrixRef:
    profile_home: Path
    store_id: str
    target: str
    account_key: str
    owner_device: str
    generation: str | None = None
