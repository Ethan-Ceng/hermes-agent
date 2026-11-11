"""Captured Discord ledger ownership and bounded Core units of work."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscordRef:
    profile_home: Path
    store_id: str
    target: str
    plugin_id: str = "discord"
