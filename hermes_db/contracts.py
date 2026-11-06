"""Small driver-free contracts at the storage composition boundary.

Session and runtime capabilities expand with their actual consumers as the
implementation tasks land. SQLite maintenance is intentionally outside them.
"""

from typing import Any, Protocol


class SessionStore(Protocol):
    def create_session(self, session_id: str, source: str, **kwargs) -> str: ...
    def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    def get_messages(self, session_id: str, **kwargs) -> list[dict[str, Any]]: ...
