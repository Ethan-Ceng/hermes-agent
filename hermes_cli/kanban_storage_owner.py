"""Captured Kanban owner references and immutable generation-based file scopes."""
from __future__ import annotations


from contextlib import contextmanager
from pathlib import Path

from hermes_db.domains.kanban.api import BoardResource
from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.kanban.owner import validate_reference, board_generations







@contextmanager
def open_board_owner(reference, *, command=None):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.domains.kanban.postgres.catalog import _lookup
    reference = validate_reference(reference)
    with _owning_profile(Path(reference["profile_home"])), acquire_profile_domain(
            "kanban_tasks", profile_home=Path(reference["profile_home"])) as resource:
        if resource.settings.backend != "postgresql" or resource.scope.require_store_id() != reference["store_id"]:
            raise StorageConfigurationError("Kanban Board owner backend or store_id changed")
        from hermes_db.core.values import resource_key
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

# File locations follow the captured generation, independently of a Board rename.

from contextvars import ContextVar
from dataclasses import dataclass
import os

_current_files = ContextVar("kanban_board_files", default=None)


@dataclass(frozen=True)
class BoardFiles:
    home: Path
    board_id: str
    slug: str


@contextmanager
def board_files(store):
    token = _current_files.set(BoardFiles(store.scope.profile_home, store.board_id, store.slug))
    try:
        yield
    finally:
        _current_files.reset(token)


def _captured():
    frame = _current_files.get()
    if frame is not None:
        return frame
    from agent.runtime_kanban_storage import worker_binding
    binding = worker_binding()
    if binding is not None:
        owner = binding[1]["owner"]
        return BoardFiles(Path(owner["profile_home"]), owner["board_id"], owner["board"])
    return None


def content_root(frame):
    return frame.home / "kanban" / "data" / frame.board_id


def _path(frame, env_var, leaf):
    override = os.environ.get(env_var, "").strip() if env_var else ""
    return Path(override).expanduser() / frame.board_id if override else content_root(frame) / leaf


def generation_path(env_var, board, leaf):
    from hermes_cli import kanban_db as kb
    if leaf not in {"workspaces", "attachments", "logs"}:
        return None
    slug = kb._explicit_board_slug(board)
    frame = _captured()
    if frame is not None and (slug is None or slug == frame.slug):
        return _path(frame, env_var, leaf)
    from hermes_cli.db_setup import storage_backend
    if storage_backend() != "postgresql":
        return None
    from agent.runtime_session_store import is_worker_process
    if is_worker_process():
        from agent.runtime_kanban_storage import connect_worker_board
        with connect_worker_board(board=slug) as proxy:
            owner = proxy.context["owner"]
            return _path(BoardFiles(Path(owner["profile_home"]), owner["board_id"], owner["board"]), env_var, leaf)
    from hermes_cli.kanban_storage_application import connect
    with connect(board=slug) as store:
        return _path(BoardFiles(store.scope.profile_home, store.board_id, store.slug), env_var, leaf)


def managed_scratch_roots():
    from hermes_cli.db_setup import storage_backend
    from agent.runtime_kanban_storage import worker_binding
    frame = _captured()
    from agent.runtime_session_store import is_worker_process
    if frame is None and is_worker_process() and storage_backend() == "postgresql":
        from agent.runtime_kanban_storage import connect_worker_board
        with connect_worker_board() as proxy:
            owner = proxy.context["owner"]
            frame = BoardFiles(Path(owner["profile_home"]), owner["board_id"], owner["board"])
    if worker_binding() is not None or (is_worker_process() and frame is not None):
        return [(_path(frame, "HERMES_KANBAN_WORKSPACES_ROOT", "workspaces"), frame.slug)]
    if frame is None and storage_backend() != "postgresql":
        return []
    from hermes_cli.db_domains import acquire_profile_domain
    with acquire_profile_domain("kanban_tasks", profile_home=frame.home if frame else None) as resource, resource.read() as conn:
        boards = board_generations(conn, resource.scope.require_store_id())
        home = resource.scope.profile_home
    return [(_path(BoardFiles(home, row.board_id, row.slug), "HERMES_KANBAN_WORKSPACES_ROOT", "workspaces"), row.slug) for row in boards]


@contextmanager
def board_operation_scope(store):
    from hermes_cli.db_setup import _owning_profile
    with _owning_profile(store.scope.profile_home), board_files(store):
        yield
