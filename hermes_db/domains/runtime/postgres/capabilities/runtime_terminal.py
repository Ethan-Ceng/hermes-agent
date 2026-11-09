"""Read-only private evidence for an authenticated edge's exact retry."""

import json

from hermes_db.domains.runtime.postgres.operations.runtime import _retired_replay
from hermes_db.domains.runtime.postgres.queries import runtime, terminal
from hermes_state_runtime import _json, _text, admission_fingerprint
from hermes_state_runtime import RuntimeStoreError


class RuntimeTerminal:
    def find_api_run(self, run_id, *, admission_id=None):
        from sqlalchemy import select
        from hermes_db.tables.runtime import session_admissions
        with self._store._read() as conn:
            if admission_id is not None:
                row = runtime.admission(conn, self.scope, admission_id)
                rows = [row] if row is not None and row["principal_id"] == "api" else []
            else:
                rows = [dict(row) for row in conn.execute(select(session_admissions).where(
                    session_admissions.c.store_id == self.scope.require_store_id(),
                    session_admissions.c.principal_id == "api", session_admissions.c.request_id == run_id)).mappings()]
                rows.extend(terminal.api_admissions(conn, self.scope, run_id))
        if len(rows) > 1:
            raise RuntimeStoreError("admission_conflict")
        return runtime.public_row(rows[0]) if rows else None

    def completion_replay(self, *, epoch, row):
        with self._store._read() as conn:
            runtime.require_epoch(conn, self.scope, epoch)
            current = runtime.admission(conn, self.scope, row["admission_id"])
            if current is None:
                raise RuntimeStoreError("not_found")
            if current["owner_epoch"] != epoch or current["generation"] != row["generation"]:
                raise RuntimeStoreError("stale_generation")
            if current["status"] != "terminal":
                return None
            saved = terminal.result(conn, self.scope, row["admission_id"])
            if saved is None:
                raise RuntimeStoreError("storage_unavailable")
            return runtime.public_row(current), saved["result"].get("final_response") or ""

    def current_result(self, admission_id):
        with self._store._read() as conn:
            row = runtime.admission(conn, self.scope, admission_id)
            if row is None:
                raise RuntimeStoreError("not_found")
            return terminal.result(conn, self.scope, admission_id) if row["status"] == "terminal" else None

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
