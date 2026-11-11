"""Pure Board owner references and scoped generation queries on a supplied connection."""
from __future__ import annotations
from pathlib import Path
from hermes_db.errors import StorageConfigurationError

_FIELDS = {"version", "backend", "profile_home", "store_id", "board_id", "board", "target"}

def board_reference(store):
    from hermes_db.core.values import resource_key
    return {"version": 2, "backend": "postgresql", "profile_home": str(store.scope.profile_home),
            "store_id": store.scope.require_store_id(), "board_id": store.board_id, "board": store.slug,
            "target": resource_key(store._transactions)}

def validate_reference(reference):
    from hermes_db.domains.kanban.rules import _require_slug
    if (not isinstance(reference, dict) or set(reference) != _FIELDS or type(reference["version"]) is not int
            or reference["version"] != 2 or reference["backend"] != "postgresql"
            or any(not isinstance(reference[key], str) or not 0 < len(reference[key]) <= 4096
                   for key in _FIELDS - {"version"}) or not Path(reference["profile_home"]).is_absolute()):
        raise StorageConfigurationError("Invalid Kanban Board owner reference")
    _require_slug(reference["board"])
    return reference


def board_generations(conn, store_id):
    from sqlalchemy import select
    from hermes_db.tables.kanban import kanban_boards
    return list(conn.execute(select(kanban_boards.c.board_id, kanban_boards.c.slug).where(
        kanban_boards.c.store_id == store_id)))
