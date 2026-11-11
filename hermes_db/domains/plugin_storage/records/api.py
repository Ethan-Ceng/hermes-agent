"""Plugin references pin Profile/database identity and namespace across thread hops."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginRef:
    profile_home: Path
    store_id: str
    target: str
    plugin_id: str
    namespace: str
