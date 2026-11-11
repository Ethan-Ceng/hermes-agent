"""Owner-resolved Board selection for root compute and its read-only descendants."""

import json
from pathlib import Path

from hermes_state_runtime import RuntimeStoreError


def _root_policy(authority, params):
    from gateway.session_policy import policy_for_source
    from hermes_db.domains.runtime.access import runtime_for_store
    from hermes_db.domains.runtime.receipts import CHILD_SEPARATOR
    execution = params["execution_id"]
    root = execution.split(CHILD_SEPARATOR, 1)[0]
    session_id = params["session_id"]
    if root != execution:
        session_id = runtime_for_store(authority.db).worker_session(root)
        if not session_id:
            raise RuntimeStoreError("permission_denied")
    live = authority.sessions.get(authority.logical_owner(session_id))
    return policy_for_source(authority.runner, live.source) if live is not None else None


def _selection(params):
    payload = params["payload"]
    target = payload if params["operation"] == "board.resolve" else payload.get("target")
    allowed = {"board"} if params["operation"] == "board.resolve" else {"board", "board_id"}
    if not isinstance(target, dict) or set(target) != allowed:
        raise RuntimeStoreError("invalid_params")
    if target["board"] is not None and not isinstance(target["board"], str):
        raise RuntimeStoreError("invalid_params")
    if "board_id" in allowed and not isinstance(target["board_id"], str):
        raise RuntimeStoreError("invalid_params")
    return target


def frozen_context(connection, ref, params):
    from hermes_cli import kanban_db as kb
    from hermes_cli.db_setup import _owning_profile
    from hermes_cli.db_domains import acquire_profile_domain
    from hermes_db.health import profile_home_for_store
    from hermes_db.domains.kanban.postgres.catalog import _lookup
    policy = _root_policy(connection.authority, params)
    if policy is not None and policy.source == "kanban" and policy.kanban_json:
        context = json.loads(policy.kanban_json)
        if not isinstance(context, dict) or "owner" not in context:
            raise RuntimeStoreError("permission_denied")
        if params["operation"] == "board.resolve" or "target" in params["payload"]:
            target = _selection(params)
            if target["board"] not in (None, context["owner"]["board"]) or target.get(
                    "board_id", context["owner"]["board_id"]) != context["owner"]["board_id"]:
                raise RuntimeStoreError("permission_denied")
        return context
    target = _selection(params)
    home = Path(profile_home_for_store(connection.authority.db))
    with _owning_profile(home), acquire_profile_domain("kanban_tasks", profile_home=home) as resource:
        slug = kb._explicit_board_slug(target["board"]) or kb.get_current_board()
        with resource.read() as conn:
            row = _lookup(conn, resource, slug)
        if (row is None and slug != "default") or (row is not None and row["archived"]):
            raise RuntimeStoreError("not_found")
        board_id = row["board_id"] if row is not None else "default"
        if target.get("board_id", board_id) != board_id:
            raise RuntimeStoreError("stale_generation")
        from hermes_db.domains.kanban.api import BoardResource
        from hermes_db.integration.kanban_owner import board_reference
        with BoardResource(resource, board_id, slug) as board:
            return {"board": slug, "owner": board_reference(board)}
