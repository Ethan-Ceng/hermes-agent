"""Resolve a trusted dispatcher claim against its Board owner's selected backend."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from hermes_state_runtime import RuntimeStoreError

CLAIM_FIELDS = {"board", "task_id", "run_id", "claim_lock"}
CLAIM_SHAPES = (CLAIM_FIELDS, CLAIM_FIELDS | {"db"}, CLAIM_FIELDS | {"owner"})


def claim_request_id(params):
    identity = [params.get("board"), params.get("task_id"), params.get("run_id")]
    if "owner" in params:
        owner = params["owner"]
        identity = ["postgresql", owner["target"], owner["store_id"], owner["board_id"], params.get("task_id"), params.get("run_id")]
    return "kanban:" + json.dumps(identity, separators=(",", ":"))


def validate_claim_params(params):
    if (not isinstance(params, dict) or set(params) not in CLAIM_SHAPES
            or any(not isinstance(params[key], str) or not params[key] for key in ("board", "task_id", "claim_lock"))
            or type(params["run_id"]) is not int):
        raise RuntimeStoreError("invalid_params")
    if "owner" in params:
        from hermes_db.domains.kanban.routing.owner import validate_reference
        from hermes_db.errors import StorageConfigurationError
        try:
            validate_reference(params["owner"])
            if params["owner"]["board"] != params["board"]:
                raise RuntimeStoreError("invalid_params")
        except StorageConfigurationError as error:
            raise RuntimeStoreError("invalid_params") from error


def _assignee_home(task, authority):
    from hermes_cli.profiles import resolve_profile_env
    if Path(resolve_profile_env(task.assignee)).resolve() != Path(authority.profile_id).resolve():
        raise RuntimeStoreError("profile_mismatch")


def _describe(conn, task, params, retry, storage):
    from hermes_cli import kanban_db as kb
    skills = list(task.skills or ())
    if retry == "review":
        skills = list(dict.fromkeys([*skills, "sdlc-review"]))
    return task, kb.build_worker_context(conn, task.id), skills, storage, str(kb.workspaces_root(board=params["board"]).resolve())


def _postgresql_claim(params, authority):
    from hermes_cli import kanban_db as kb
    from hermes_db.domains.kanban.routing.owner import open_board_owner, validate_reference
    from hermes_db.domains.kanban.postgres.operations.owner import inspect_claim
    validate_reference(params["owner"])
    if params["owner"]["board"] != params["board"]:
        raise RuntimeStoreError("invalid_kanban_claim")
    request_id = claim_request_id(params)
    with open_board_owner(params["owner"]) as store:
        task_row, retry = inspect_claim(store, params, request_id)
        task = kb.Task.from_row(task_row)
        _assignee_home(task, authority)
        return _describe(store, task, params, retry, {"owner": dict(params["owner"])})


def describe_claim(params, authority):
    from hermes_cli import kanban_db as kb
    from hermes_db.errors import StorageConfigurationError
    try:
        board = kb._require_slug(params["board"])
        if "owner" in params:
            return _postgresql_claim(params, authority)
        # A path only identifies the legacy SQLite Board. It never selects a PG owner.
        from hermes_cli.db_setup import storage_backend
        if storage_backend() == "postgresql":
            raise RuntimeStoreError("invalid_kanban_claim")
        path = Path(params["db"]).resolve(strict=True) if "db" in params else kb.kanban_db_path(board=board).resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            task = kb.get_task(conn, params["task_id"])
            run = conn.execute("SELECT * FROM task_runs WHERE id=?", (params["run_id"],)).fetchone()
            if (task is None or run is None or task.status != "running" or run["status"] != "running"
                    or task.current_run_id != params["run_id"] or run["task_id"] != task.id
                    or task.claim_lock != params["claim_lock"] or run["claim_lock"] != task.claim_lock):
                raise RuntimeStoreError("stale_kanban_claim")
            _assignee_home(task, authority)
            bound = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='owner_admitted' "
                                 "ORDER BY id DESC LIMIT 1", (task.id, task.current_run_id)).fetchone()
            request = "kanban:" + json.dumps([board, task.id, task.current_run_id], separators=(",", ":"))
            if bound and json.loads(bound[0])["request_id"] != request:
                raise RuntimeStoreError("stale_kanban_claim")
            return _describe(conn, task, params, kb._retry_status_for_run(conn, task.id, task.current_run_id), {"db": str(path)})
    except (ValueError, OSError, sqlite3.Error, StorageConfigurationError) as error:
        raise RuntimeStoreError("invalid_kanban_claim") from error


def admit_postgresql_claim(context, params, receipt):
    from hermes_db.domains.kanban.routing.owner import open_board_owner
    from hermes_db.domains.kanban.postgres.operations.owner import admit_claim
    with open_board_owner(context["owner"]) as store:
        admit_claim(store, params, receipt)
