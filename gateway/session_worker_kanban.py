"""Authenticated Board RPC; mutation ACKs belong to the Board's own receipt transaction."""

import asyncio

from hermes_db.domains.kanban_owner import open_board_owner
from hermes_db.domains.kanban_wire import pack
from hermes_db.errors import StorageError
from hermes_db.operations.kanban_command_receipts import CommandReceipt, CommandReplay, refusal
from hermes_state_keys import admission_fingerprint
from hermes_state_runtime import RuntimeStoreError


async def worker_kanban(connection, ref, params, *, command):
    from gateway.session_authorities import require_serving
    from gateway.session_worker import _SCOPE
    from gateway.session_worker_kanban_operations import READS, COMMANDS
    require_serving(connection.authority)
    fields = _SCOPE | {"epoch", "operation", "payload"} | ({"command_id"} if command else set())
    if (set(params) != fields or not isinstance(params["operation"], str) or params["operation"] not in (COMMANDS if command else READS)
            or not isinstance(params["payload"], dict)):
        raise RuntimeStoreError("invalid_params")
    if "worker:adopt" not in connection.actor.capabilities:
        raise RuntimeStoreError("permission_denied")
    if command:
        if "/child:" in params["execution_id"]:
            raise RuntimeStoreError("permission_denied")
        command_id = params["command_id"]
        if not isinstance(command_id, str) or len(command_id) != 32 or any(char not in "0123456789abcdef" for char in command_id):
            raise RuntimeStoreError("invalid_params")
    return await asyncio.to_thread(_execute, connection, ref, params, command)


def _execute(connection, ref, params, command):
    from hermes_cli.kanban_db import ArtifactPreservationError
    from gateway.session_worker_recall import verify_read
    from gateway.session_worker_kanban_context import frozen_context
    from gateway.session_worker_kanban_operations import invoke
    verify_read(connection, ref, params)
    context = frozen_context(connection, ref, params)
    if params["operation"] == "board.resolve":
        return pack(context)
    from hermes_db.health import profile_home_for_store
    from hermes_db.integration.transfer.move_values import resource_key
    database = connection.authority.db
    context = dict(context, principal=connection.actor.subject, session_store={
        "home": str(profile_home_for_store(database)), "store_id": database.scope.require_store_id(),
        "target": resource_key(database._transactions)})
    if params["operation"] == "attachment.chunk":
        from gateway.session_worker_kanban_upload import write_chunk
        with open_board_owner(context["owner"]) as store:
            return pack(write_chunk(dict(context, board_target=resource_key(store._transactions)), params, connection.actor.subject))
    if not command:
        with open_board_owner(context["owner"]) as store:
            return pack(invoke(store, context, params, params["operation"], params["payload"]))
    digest = admission_fingerprint(canonical_target=context["owner"]["board_id"], payload={
        "owner": context["owner"], "principal": connection.actor.subject,
        **{key: params[key] for key in ("profile_id", "execution_id", "generation", "operation", "payload")}})
    receipt = CommandReceipt(params["command_id"], digest)
    try:
        with open_board_owner(context["owner"], command=receipt) as store:
            context = dict(context, board_target=resource_key(store._transactions))
            with store.read() as conn:
                receipt.check_replay(conn, store)
            try:
                result = invoke(store, context, params, params["operation"], params["payload"])
            except (StorageError, RuntimeStoreError):
                raise
            except (ValueError, ArtifactPreservationError) as error:
                result = refusal(error)
            if not receipt.committed:
                with store.write() as conn:
                    store.command_result(conn, result)
            return pack(result)
    except CommandReplay as replay:
        return pack(replay.result)
