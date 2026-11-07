"""Kanban's independent command receipt slot inside the existing private worker outbox."""

import json
import uuid


class RuntimeSessionKanbanMixin:
    def _has_pending_receipt(self):
        return bool(self.journal["pending"] or self.journal.get("kanban_pending"))

    def kanban_read(self, operation, payload):
        return self._read_rpc("worker.kanban.read", operation=operation, payload=payload)

    def kanban_command(self, operation, payload):
        from agent.runtime_session_store import WorkerPersistenceError
        with self.lock:
            if self.failure:
                raise WorkerPersistenceError(self.failure)
            if self._has_pending_receipt():
                raise WorkerPersistenceError("pending_receipt")
            entry = {"command_id": uuid.uuid4().hex, "operation": operation, "payload": payload}
            candidate = json.loads(json.dumps(self.journal, allow_nan=False))
            candidate["kanban_pending"] = json.loads(json.dumps(entry, allow_nan=False))
            try:
                self._save(candidate)
            except Exception as error:
                self.failure = str(error)
                raise
            self.journal = candidate
            return self.retry_pending()[0]

    def _retry_kanban_pending(self):
        entry = self.journal.get("kanban_pending")
        if entry is None:
            return []
        result = self.rpc("worker.kanban.command", **self.scope, **entry)
        candidate = dict(self.journal, kanban_pending=None)
        self._save(candidate)
        self.journal = candidate
        return [result]
