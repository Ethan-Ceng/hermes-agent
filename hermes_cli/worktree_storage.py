"""Credential-free owning-store references for retained worktrees; never infer PG from a db path."""

import base64
from dataclasses import dataclass
import json
import logging
from pathlib import Path

from hermes_db.errors import StorageError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileStore:
    home: Path
    store_id: str
    target: str

    def encode(self):
        payload = json.dumps([1, str(self.home), self.store_id, self.target], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode("ascii")


def capture_worktree_store(profile_home=None):
    from hermes_constants import get_hermes_home
    from hermes_cli.db_setup import storage_backend, resolve_db_configuration
    home = Path(profile_home if profile_home is not None else get_hermes_home()).resolve()
    if storage_backend(home) == "sqlite":
        return home / "state.db"
    from hermes_db.infra.backends.postgresql.engine import get_engine
    from hermes_db.core.values import resource_key
    from hermes_db.infra.backends.postgresql.transactions import Transactions
    from hermes_db.tables.metadata import SCHEMA
    settings, scope = resolve_db_configuration(home)
    pg = settings.postgresql
    return ProfileStore(home, scope.require_store_id(), resource_key(Transactions(get_engine(pg), pg.schema, schema_token=SCHEMA)))


def decode_store(token):
    if len(token) > 8192:
        raise ValueError("Worktree store reference is too large")
    value = json.loads(base64.b64decode(token, altchars=b"-_", validate=True))
    if not isinstance(value, list) or len(value) != 4 or value[0] != 1 or not all(isinstance(part, str) and part for part in value[1:]):
        raise ValueError("Unknown worktree store reference")
    home = Path(value[1])
    if not home.is_absolute():
        raise ValueError("Worktree owner Profile must be absolute")
    return ProfileStore(home, value[2], value[3])


def lock_suffix(reference):
    if isinstance(reference, ProfileStore):
        return f" store={reference.encode()}"
    return "" if reference is None else f" db={reference}"


def sqlite_locator_selected(db_path):
    from hermes_cli.db_setup import storage_backend
    # This legacy field explicitly names a SQLite file. It can only be refused here, never reinterpreted as PG.
    return storage_backend(Path(db_path).resolve().parent) == "sqlite"


def _active(value):
    try:
        value = json.loads(value)
    except (TypeError, ValueError):
        return True
    return not isinstance(value, dict) or value.get("status") in (None, "active")


def _observations(reference, worktree_path):
    from hermes_cli.worktree_ops import _inside_tree
    from hermes_cli.db_observations import worktree_sessions
    rows, meta = worktree_sessions(reference.home, reference.store_id, reference.target)
    inside = _inside_tree(worktree_path)
    return [row for row in rows if inside(row["cwd"])], {key for key, value in meta if _active(value)}


def retained_tree_is_live(reference, worktree_path, *, pending_only=False):
    try:
        rows, _ = _observations(reference, worktree_path)
        return any(row["pending"] or (not pending_only and (row["message_count"] or 0) > 0) for row in rows)
    except (StorageError, OSError) as error:
        logger.warning("PG retained worktree observation unavailable (%s); keeping tree", type(error).__name__)
        return True


def tree_still_served(reference, worktree_path):
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.worktree_ops import _cron_bound_to_tree
    try:
        rows, active = _observations(reference, worktree_path)
        if any(row["ended_at"] is None or any(prefix + row["id"] in active for prefix in ("loop:", "heartbeat:", "goal:")) for row in rows):
            return "session"
        with _owning_profile(reference.home):
            return "cron" if _cron_bound_to_tree(worktree_path, {row["chat_id"] for row in rows if row["chat_id"] is not None}) else None
    except (StorageError, OSError) as error:
        logger.warning("PG served worktree observation unavailable (%s); keeping tree", type(error).__name__)
        return "unreadable"
