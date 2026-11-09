"""Adopted PG Board worker bindings use named owner RPC, including liveness evidence."""

import os

from hermes_db.domains.kanban.routing.wire import unpack, CommandRefusal


def _owner_call(operation, payload, *, command):
    from agent.runtime_session_store import current_worker_store, call_off_event_loop
    store = current_worker_store()
    method = store.kanban_command if command else store.kanban_read
    result = unpack(call_off_event_loop(method, operation, payload))
    if isinstance(result, CommandRefusal):
        result.raise_error()
    return result


def claim_live():
    return _owner_call("worker.claim_live", {}, command=False)


def record_result(code, last_output):
    return _owner_call("worker.result", {"code": code, "last_output": last_output}, command=True)


def bind(context):
    from hermes_db.domains.kanban.routing.worker import bind_worker_board
    bind_worker_board(context)
    ttl = _owner_call("worker.bind", {}, command=True)
    _watch_submitter()
    return ttl


def _watch_submitter():
    from agent.memory_provider import spawn_context_thread
    from agent.runtime_session_store import WorkerPersistenceError
    from gateway.session_kanban import _TURNS_DONE
    from hermes_cli.kanban_db_dispatch import _worker_alive

    def watch():
        while not _TURNS_DONE.wait(1):
            try:
                row = _owner_call("worker.submitter", {}, command=False)
            except (WorkerPersistenceError, OSError):
                continue
            if row and row["worker_pid"] and row["worker_pid"] != os.getpid() and not _worker_alive(
                    row["worker_pid"], row["worker_started_at"]):
                os._exit(1)

    spawn_context_thread(watch, name="kanban-submitter-watch").start()


def record_loss(context, reason, *, pid, bound):
    from hermes_db.domains.kanban.routing.owner import open_board_owner
    from hermes_db.domains.kanban.postgres.operations.owner import record_loss as write_loss
    with open_board_owner(context["owner"]) as store:
        write_loss(store, context, reason, pid=pid, bound=bound)
