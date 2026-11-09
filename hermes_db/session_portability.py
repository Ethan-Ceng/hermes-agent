"""Current JSON export/import APIs with a consistent scoped read snapshot."""

from copy import deepcopy

from sqlalchemy import select

from hermes_db.message_codec import codec
from hermes_db.integration.postgres.operations import portability
from hermes_db.integration.transfer.portability_values import values
from hermes_db.repositories import messages, session_queries, sessions
from hermes_db.tables.conversations import sessions as table
from hermes_state_portability import _export_timings


def _export(conn, scope, session, include_compacted=False, include_inactive=False):
    from hermes_db.session_message_reads import _display_page
    from hermes_db.tables.conversations import messages as rows

    if include_compacted and not include_inactive:
        transcript = _display_page(conn, scope, session["id"], None, 0, False)
    else:
        conditions = [] if include_inactive else [rows.c.active == 1]
        transcript = messages.select_rows(conn, scope, [session["id"]], *conditions)
    public = [codec._row_to_message_dict(row, warn_context="export", summary_flag=True) for row in transcript]
    return {**session, "messages": public, "timings": _export_timings(public, session["id"])}


class SessionPortability:
    def export_session(self, session_id, include_compacted=False, include_inactive=False):
        self.flush_for_read()
        with self._read() as conn:
            row = sessions.get_session(conn, self.scope, session_id)
            return _export(conn, self.scope, row, include_compacted, include_inactive) if row else None

    def export_session_lineage(self, session_id, include_compacted=False, include_inactive=False):
        self.flush_for_read()
        with self._read() as conn:
            ids = messages.resume_lineage(conn, self.scope, session_id)
            rows = sessions.get_sessions(conn, self.scope, ids)
            segments = [_export(conn, self.scope, rows[sid], include_compacted, include_inactive) for sid in ids if sid in rows]
        if not segments:
            return None
        public = [row for segment in segments for row in segment["messages"]]
        return {**segments[-1], "segments": segments, "lineage_session_ids": [segment["id"] for segment in segments],
            "message_count": len(public), "messages": public, "timings": _export_timings(public, session_id)}

    def export_all(self, source=None, include_compacted=False, include_inactive=False):
        self.flush_for_read()
        with self._read() as conn:
            statement = select(table.c.id).where(table.c.store_id == self.scope.require_store_id())
            if source:
                statement = statement.where(table.c.source == source)
            ids = conn.execute(statement.order_by(session_queries.last_activity(conn).desc(), table.c.started_at.desc(), table.c.id.desc())
                .limit(100000)).scalars().all()
            rows = {}
            for start in range(0, len(ids), 1000):
                rows.update({row["id"]: row for row in session_queries.hydrate(conn, self.scope, ids[start:start + 1000])})
            return [_export(conn, self.scope, rows[sid], include_compacted, include_inactive) for sid in ids]

    def import_sessions(self, payload):
        if not isinstance(payload, list):
            raise ValueError("sessions must be a list")
        if len(payload) > values._IMPORT_MAX_SESSIONS:
            raise ValueError(f"sessions must contain at most {values._IMPORT_MAX_SESSIONS} entries")
        normalized, errors = values._validate_import_payload(deepcopy(payload))
        if errors:
            return {"ok": False, "imported": 0, "skipped": 0, "detached": 0, "errors": errors}
        with self._write() as conn:
            return portability.import_current(conn, self.scope, normalized)
