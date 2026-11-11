"""Queue identity pins Profile/database and remote destination, excluding API credentials."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetainQueueRef:
    profile_home: Path
    store_id: str
    target: str
    destination_id: str
    plugin_id: str = "retaindb"
