"""A native submitter reads its exact saved attempt through the owning session authority."""

import asyncio
import json

from hermes_db.health import persisted_profile_id
from hermes_state_runtime import RuntimeStoreError


async def result_task(connection, params):
    from gateway.session_kanban_policy import validate_claim_params
    if not connection.native_owner or "session:create" not in connection.actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    if connection.actor.profile_id != connection.authority.profile_id:
        raise RuntimeStoreError("profile_mismatch")
    validate_claim_params(params)
    return await asyncio.to_thread(_result, connection, params)


def _result(connection, params):
    from gateway.session_local_recovery import local_identity
    from gateway.session_policy import restore_policy
    from hermes_db.integration.local_access import local_receipt
    from gateway.session_kanban_policy import claim_request_id
    authority = connection.authority
    request_id = claim_request_id(params)
    session_id = local_identity(persisted_profile_id(authority), connection.actor.subject, request_id)
    saved = local_receipt(authority.db, session_id)
    if saved is None:
        raise RuntimeStoreError("not_found")
    context = json.loads(restore_policy(saved["policy"]).kanban_json or "{}")
    if any(context.get(key) != value for key, value in params.items()):
        raise RuntimeStoreError("permission_denied")
    if "owner" in context:
        from hermes_db.integration.kanban_owner import open_board_owner
        from hermes_db.domains.kanban.postgres.owners import worker_result
        with open_board_owner(context["owner"]) as board:
            return worker_result(board, context)
    from gateway.session_kanban import worker_result
    return worker_result(context["db"], context)
