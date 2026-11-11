"""Kanban business values and immutable, caller-resolved Board handles."""

from contextlib import contextmanager
from dataclasses import dataclass

from hermes_db.domains.resource import DomainResource
from hermes_db.errors import StorageConfigurationError




@dataclass(frozen=True)
class KanbanValues:
    task: object
    run: object
    comment: object
    attachment: object
    event: object
    live_claim_error: type[Exception]
    hallucinated_cards_error: type[Exception]
    empty_completion_error: type[Exception]
    artifact_preservation_error: type[Exception]
    attachment_too_large: type[Exception]
    dispatch_result: object
    swarm_created: object


@dataclass(frozen=True)
class KanbanCodec:
    pack: object
    unpack: object
    refusal: object
    board_reference: object


class KanbanResource(DomainResource):
    def __init__(self, backend, *, result_values, mutation_guard, policy, processes, observers, files, operation_scope, codec):
        super().__init__("kanban_tasks", backend)
        self.result_values = result_values
        self.mutation_guard = mutation_guard
        self.policy = policy
        self.processes = processes
        self.observers = observers
        self.files = files
        self.operation_scope = operation_scope
        self.codec = codec


class BoardResource(DomainResource):
    def __init__(self, resource, board_id, slug, *, command=None):
        super().__init__(resource.name, resource._backend)
        self.result_values = resource.result_values
        self.mutation_guard = resource.mutation_guard
        self.policy = resource.policy
        self.processes = resource.processes
        self.observers = resource.observers
        self.files = resource.files
        self.operation_scope = resource.operation_scope
        self.codec = resource.codec
        self.board_id = board_id
        self.slug = slug
        self.command = command

    @contextmanager
    def write(self, *, lock_timeout=None):
        from hermes_db.domains.kanban.postgres.repository import lock_board
        from hermes_db.domains.kanban.postgres.files import lock_files
        self.mutation_guard()
        with super().write(lock_timeout=lock_timeout) as conn:
            lock_files(conn, self)
            if self.slug == self.board_id == "default":
                from hermes_db.domains.kanban.postgres.catalog import _lookup, _registry_lock, _save
                _registry_lock(conn, self)
                row = _lookup(conn, self, self.slug)
                if row is None:
                    _save(conn, self, self.slug, None, False)
                elif row["board_id"] != self.board_id:
                    raise StorageConfigurationError("Default Board owner generation changed")
            lock_board(conn, self)
            if self.command is not None and not self.command.committed:
                self.command.check_replay(conn, self)
            yield conn
        if self.command is not None:
            self.command.after_commit(conn)

    def command_result(self, conn, result):
        return self.command.record(conn, self, result) if self.command is not None else result


    def _operation_scope(self):
        return self.operation_scope(self)


    def _flag_phantom_prose_refs(self, task_id, run_id, summary, result, verified_cards):
        from hermes_db.domains.kanban.postgres.completion import _flag_phantom_prose_refs
        with self._operation_scope():
            return _flag_phantom_prose_refs(self, task_id, run_id, summary, result, verified_cards)

    def _gate_created_cards(self, task_id, created_cards, preview_text):
        from hermes_db.domains.kanban.postgres.completion import _gate_created_cards
        with self._operation_scope():
            return _gate_created_cards(self, task_id, created_cards, preview_text)

    def _gate_empty_completion(self, task_id, *, result, summary):
        from hermes_db.domains.kanban.postgres.completion import _gate_empty_completion
        with self._operation_scope():
            return _gate_empty_completion(self, task_id, result=result, summary=summary)

    def _record_task_failure(self, task_id, error, *, outcome, failure_limit=None, force_trip=False, release_claim=False, end_run=False, event_payload_extra=None, infrastructure=False, expected_run_id=None):
        from hermes_db.domains.kanban.postgres.runs import _record_task_failure
        with self._operation_scope():
            return _record_task_failure(self, task_id, error, outcome=outcome, failure_limit=failure_limit, force_trip=force_trip, release_claim=release_claim, end_run=end_run, event_payload_extra=event_payload_extra, infrastructure=infrastructure, expected_run_id=expected_run_id)

    def get_task(self, task_id):
        from hermes_db.domains.kanban.postgres.catalog import get_task
        with self._operation_scope():
            return get_task(self, task_id)

    def latest_run(self, task_id):
        from hermes_db.domains.kanban.postgres.runs import latest_run
        with self._operation_scope():
            return latest_run(self, task_id)

    def list_tasks(self, *, assignee=None, status=None, tenant=None, session_id=None, include_archived=False, limit=None, order_by=None, workflow_template_id=None, current_step_key=None):
        from hermes_db.domains.kanban.postgres.catalog import list_tasks
        with self._operation_scope():
            return list_tasks(self, assignee=assignee, status=status, tenant=tenant, session_id=session_id, include_archived=include_archived, limit=limit, order_by=order_by, workflow_template_id=workflow_template_id, current_step_key=current_step_key)


    def recompute_ready(self, failure_limit=None):
        from hermes_db.domains.kanban.postgres.catalog import recompute_ready
        with self._operation_scope():
            return recompute_ready(self, failure_limit)




    def set_branch_name(self, task_id, branch_name):
        from hermes_db.domains.kanban.postgres.workspaces import set_branch_name
        with self._operation_scope():
            return set_branch_name(self, task_id, branch_name)
