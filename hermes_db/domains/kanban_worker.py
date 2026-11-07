"""Process-bound Board proxy for an already adopted compute worker, never a DB handle."""

from copy import deepcopy
import os

from hermes_db.errors import StorageClosedError, StorageConfigurationError, StorageNotReadyError

_binding = None


def bind_worker_board(context):
    from agent.runtime_session_store import current_worker_store, WorkerPersistenceError
    from hermes_db.domains.kanban_owner import validate_reference
    global _binding
    store = current_worker_store()
    if store is None or store.scope["pid"] != os.getpid():
        raise WorkerPersistenceError("permission_denied")
    validate_reference(context["owner"])
    if _binding is not None and (_binding[0] is not store or _binding[1] != context):
        raise WorkerPersistenceError("kanban_worker_already_bound")
    _binding = (store, deepcopy(context))
    return store


def worker_binding():
    from agent.runtime_session_store import is_worker_process
    return _binding if is_worker_process() else None


def connect_worker_board(db_path=None, *, board=None):
    binding = worker_binding()
    if binding is None:
        return None
    if db_path is not None or (board is not None and board != binding[1]["board"]):
        raise StorageConfigurationError("Worker Board selector must match its adopted owner policy")
    return WorkerBoardResource(*binding)


class WorkerBoardResource:
    def __init__(self, worker_store, context):
        self.worker_store = worker_store
        self.context = context
        self.slug = context["board"]
        self.board_id = context["owner"]["board_id"]
        self.pid = os.getpid()
        self.closed = False

    def invoke(self, operation, args, kwargs):
        from agent.runtime_session_store import call_off_event_loop
        from gateway.session_worker_kanban_operations import READS, COMMANDS
        from hermes_db.domains.kanban_wire import pack, unpack, CommandRefusal
        if self.closed or self.pid != os.getpid():
            raise StorageClosedError("Worker Board resource is closed or belongs to another process")
        if operation not in READS | COMMANDS:
            raise StorageNotReadyError(f"Kanban worker operation {operation} is not implemented")
        payload = {"args": pack(args), "kwargs": pack(kwargs)}
        method = self.worker_store.kanban_read if operation in READS else self.worker_store.kanban_command
        result = unpack(call_off_event_loop(method, operation, payload))
        if isinstance(result, CommandRefusal):
            result.raise_error()
        return result

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
