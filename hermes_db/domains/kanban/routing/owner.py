"""Trusted Board owner coordinates cross Profile execution without a SQLite path or DSN."""

from contextlib import contextmanager
from pathlib import Path

from hermes_db.domains.kanban.api import BoardResource
from hermes_db.errors import StorageConfigurationError

_FIELDS = {"version", "backend", "profile_home", "store_id", "board_id", "board", "target"}


def board_reference(store):
    from hermes_db.integration.transfer.move_values import resource_key
    return {"version": 2, "backend": "postgresql", "profile_home": str(store.scope.profile_home),
            "store_id": store.scope.require_store_id(), "board_id": store.board_id, "board": store.slug,
            "target": resource_key(store._transactions)}


def validate_reference(reference):
    from hermes_cli.kanban_db import _require_slug
    if (not isinstance(reference, dict) or set(reference) != _FIELDS or type(reference["version"]) is not int
            or reference["version"] != 2 or reference["backend"] != "postgresql"
            or any(not isinstance(reference[key], str) or not 0 < len(reference[key]) <= 4096
                   for key in _FIELDS - {"version"}) or not Path(reference["profile_home"]).is_absolute()):
        raise StorageConfigurationError("Invalid Kanban Board owner reference")
    _require_slug(reference["board"])
    return reference


@contextmanager
def open_board_owner(reference, *, command=None):
    from hermes_cli.db_setup import _owning_profile
    from hermes_db.factory import acquire_profile_domain
    from hermes_db.domains.kanban.postgres.catalog import _lookup
    reference = validate_reference(reference)
    with _owning_profile(Path(reference["profile_home"])), acquire_profile_domain(
            "kanban_tasks", profile_home=Path(reference["profile_home"])) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.require_store_id() != reference["store_id"]:
            raise StorageConfigurationError("Kanban Board owner backend or store_id changed")
        from hermes_db.integration.transfer.move_values import resource_key
        if resource_key(resource._transactions) != reference["target"]:
            raise StorageConfigurationError("Kanban Board owner database target changed; reopen its owning runtime")
        with resource.read() as conn:
            row = _lookup(conn, resource, reference["board"])
        if row is None and reference["board"] == reference["board_id"] == "default":
            with BoardResource(resource, "default", "default") as board:
                board.command = command
                yield board
            return
        if row is None or row["archived"] or row["board_id"] != reference["board_id"]:
            raise StorageConfigurationError("Kanban Board owner generation was retired or replaced")
        with BoardResource(resource, row["board_id"], reference["board"], command=command) as board:
            yield board
