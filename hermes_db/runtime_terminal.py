"""Read-only private evidence for an authenticated edge's exact retry."""

import json

from hermes_db.operations.runtime import _retired_replay
from hermes_db.repositories import runtime, terminal
from hermes_state_runtime import _json, _text, admission_fingerprint


class RuntimeTerminal:
    def retry_terminal_admission(self, *, epoch, principal_id, session_id, request_id, payload, intent="queue"):
        for value in (principal_id, session_id, request_id):
            _text(value)
        digest = admission_fingerprint(canonical_target=session_id, payload={"input": json.loads(_json(payload)), "intent": intent})
        with self._store._read() as conn:
            runtime.require_epoch(conn, self.scope, epoch)
            return _retired_replay(conn, self.scope, principal_id, session_id, request_id, digest)

    def terminal_worker_receipt(self, **kwargs):
        with self._store._read() as conn:
            return terminal.worker_receipt(conn, self.scope, **kwargs)

    def terminal_api_admissions(self, request_id):
        with self._store._read() as conn:
            return terminal.api_admissions(conn, self.scope, request_id)

    def terminal_admission(self, admission_id):
        with self._store._read() as conn:
            return terminal.admission(conn, self.scope, admission_id)

    def admission_result(self, admission_id):
        with self._store._read() as conn:
            return terminal.result(conn, self.scope, admission_id)
