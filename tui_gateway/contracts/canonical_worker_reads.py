"""Owner-mediated worker reads; database selectors never cross the wire."""

from typing import Literal

from pydantic import RootModel

from .base import JsonValue, Params
from .canonical import WorkerScopeParams
from .registry import canonical_method


class WorkerRecallOptions(Params):
    query: str = ''
    role_filter: str | None = None
    limit: int | None = None
    current_session_id: str | None = None
    session_id: str | None = None
    around_message_id: int | None = None
    window: int = 5
    sort: str | None = None
    profile: str | None = None
    detail: str = 'adaptive'
    after: str | None = None
    before: str | None = None
    exclude_session_ids: list[str] | None = None


class WorkerRecallParams(WorkerScopeParams):
    epoch: int
    options: WorkerRecallOptions


class WorkerRecallResult(RootModel):
    root: str


class WorkerReadParams(WorkerScopeParams):
    epoch: int
    operation: Literal['result.owns', 'session.persisted', 'cron.usage']
    payload: dict[str, str]


class WorkerReadResult(RootModel):
    root: bool | str | None | dict[str, JsonValue]


canonical_method('worker.recall', params=WorkerRecallParams, result=WorkerRecallResult,
    doc='Read session history through the authenticated adopted execution owner.')
canonical_method('worker.read', params=WorkerReadParams, result=WorkerReadResult,
    doc='Read fixed tool metadata through the authenticated adopted execution owner.')
