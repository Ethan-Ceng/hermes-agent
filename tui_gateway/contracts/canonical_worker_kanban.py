"""Adopted worker Board RPC, with a separate durable mutation command identity."""

from pydantic import RootModel

from .base import JsonValue
from .canonical import KanbanRunParams, WorkerScopeParams
from .registry import canonical_method


class WorkerKanbanReadParams(WorkerScopeParams):
    epoch: int
    operation: str
    payload: dict[str, JsonValue]


class WorkerKanbanCommandParams(WorkerKanbanReadParams):
    command_id: str


class WorkerKanbanResult(RootModel):
    root: dict[str, JsonValue]


canonical_method("worker.kanban.read", params=WorkerKanbanReadParams, result=WorkerKanbanResult,
                 doc="Read named Board data through the adopted worker's frozen owner policy.")
canonical_method("worker.kanban.command", params=WorkerKanbanCommandParams, result=WorkerKanbanResult,
                 doc="Apply a named Board mutation once under its scoped durable command receipt.")
canonical_method("kanban.result", params=KanbanRunParams, result=WorkerKanbanResult,
                 doc="Read the native producer's exact saved Kanban attempt result through its owner.")
