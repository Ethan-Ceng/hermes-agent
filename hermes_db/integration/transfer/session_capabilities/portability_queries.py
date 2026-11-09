"""Scoped workspace, current scheduler and skill-scaffold history projections."""

import json

from sqlalchemy import func, select

from hermes_db.domains.sessions.postgres.support.message_codec import content_from_bytes
from hermes_db.repositories import runtime
from hermes_db.domains.sessions.postgres.queries import session_queries, sessions
from hermes_db.tables.conversations import messages, sessions as table
from hermes_db.tables.runtime import session_admissions
from hermes_db.core.values import decode_text
from hermes_state_keys import CRON_PRINCIPAL_ID, cron_run_from_request
from hermes_state_local import POLICY_PREFIX


def cron_identity(conn, scope, row):
    identity = cron_run_from_request(row["request_id"])
    if identity is None:
        raw = runtime.meta(conn, scope, POLICY_PREFIX + row["target_session_id"])
        if raw:
            policy = json.loads(raw)["policy"]
            job = json.loads(policy["request_json"]).get("cron_job", {}).get("id")
            if isinstance(job, str):
                identity = cron_run_from_request(row["request_id"], job)
    return {"cron_job_id": identity[0], "cron_execution_id": identity[1]} if identity else None


class SessionPortabilityQueries:
    def distinct_session_cwds(self, include_archived=False):
        conditions = [table.c.store_id == self.scope.require_store_id(), table.c.cwd.is_not(None), func.trim(table.c.cwd) != ""]
        if not include_archived:
            conditions.append(table.c.archived == 0)
        with self._read() as conn:
            rows = conn.execute(select(table.c.cwd, func.count().label("sessions"),
                func.max(func.coalesce(table.c.ended_at, table.c.started_at, 0)).label("last_active")).where(*conditions).group_by(table.c.cwd))
            return [dict(row) for row in rows.mappings()]

    def cron_run_identity(self, session_id):
        with self._read() as conn:
            row = conn.execute(select(session_admissions.c.request_id, session_admissions.c.target_session_id).where(
                session_admissions.c.store_id == self.scope.require_store_id(), session_admissions.c.principal_id == CRON_PRINCIPAL_ID,
                session_admissions.c.target_session_id == session_id).order_by(session_admissions.c.seq).limit(1)).mappings().one_or_none()
            return cron_identity(conn, self.scope, row) if row else None

    def list_cron_job_runs(self, job_id, limit=20, offset=0):
        self.flush_for_read()
        with self._read() as conn:
            rows = conn.execute(select(session_admissions.c.target_session_id, session_admissions.c.request_id).join(table,
                (table.c.store_id == session_admissions.c.store_id) & (table.c.id == session_admissions.c.target_session_id)).where(
                session_admissions.c.store_id == self.scope.require_store_id(), session_admissions.c.principal_id == CRON_PRINCIPAL_ID,
                session_admissions.c.request_id.startswith("cron:" + job_id + ":", autoescape=True), table.c.source == "cron")
                .order_by(table.c.started_at.desc(), table.c.id.desc(), session_admissions.c.seq)).mappings()
            found = {}
            for row in rows:
                identity = cron_identity(conn, self.scope, row)
                if identity and identity["cron_job_id"] == job_id:
                    found.setdefault(row["target_session_id"], identity)
            ids = list(found)[offset:][:None if limit < 0 else limit]
            return [{**row, **found[row["id"]]} for row in session_queries.hydrate(conn, self.scope, ids)]

    def list_skill_scaffolded_sessions(self, limit=200):
        from agent.skill_commands import AUTO_LOAD_SCAFFOLD_SQL_LIKE, SKILL_SCAFFOLD_SQL_LIKE

        if int(limit) == 0:
            return []
        first = select(messages.c.content).where(messages.c.store_id == table.c.store_id, messages.c.session_id == table.c.id,
            messages.c.role == "user", messages.c.content.is_not(None)).order_by(messages.c.timestamp, messages.c.id).limit(1).scalar_subquery()
        with self._read() as conn:
            rows = conn.execute(select(table.c.id, table.c.title, first.label("content")).where(
                table.c.store_id == self.scope.require_store_id(), table.c.title.is_not(None)).order_by(table.c.started_at.desc()))
            found = []
            for sid, title, raw in rows:
                content = content_from_bytes(raw)
                if isinstance(content, str) and content.lower().startswith((SKILL_SCAFFOLD_SQL_LIKE[:-1].lower(), AUTO_LOAD_SCAFFOLD_SQL_LIKE[:-1].lower())):
                    found.append({"id": sid, "title": decode_text(title), "content": content})
                    if limit >= 0 and len(found) >= limit:
                        break
            return found

    def find_foreign_import(self, origin):
        with self._read() as conn:
            return find_foreign(conn, self.scope, origin)

    def import_foreign_history(self, origin, messages, *, title, cwd, profile):
        from hermes_db.integration.postgres.operations import portability
        from hermes_db.integration.transfer.portability_values import values
        from hermes_state_ids import new_session_id

        sid = new_session_id(hex_len=12)
        normalized, errors = values._validate_import_payload([{"id": sid, "source": origin["tool"], "title": title, "cwd": cwd, "messages": messages}])
        if errors:
            raise ValueError(errors[0]["error"])
        with self._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            existing = find_foreign(conn, self.scope, origin)
            if existing:
                return {"session_id": existing, "already_imported": True}
            if title is not None and conn.scalar(select(table.c.id).where(table.c.store_id == self.scope.require_store_id(), table.c.title == title.encode("utf-8"))):
                normalized[0]["session"]["title"] = f"{title} ({sid[-12:]})"
            portability.import_row(conn, self.scope, normalized[0]["session"], normalized[0]["messages"])
            sessions.update_session(conn, self.scope, sid, {"origin_json": json.dumps({"imported_from": origin}), "profile_name": profile})
            return {"session_id": sid, "already_imported": False}


def find_foreign(conn, scope, origin):
    rows = conn.execute(select(table.c.id, table.c.origin_json).where(table.c.store_id == scope.require_store_id(),
        table.c.source == origin["tool"], table.c.origin_json.is_not(None)))
    for sid, raw in rows:
        imported = json.loads(raw).get("imported_from", {})
        if imported.get("tool") != origin["tool"]:
            continue
        foreign = origin.get("foreign_session_id")
        if foreign and foreign == imported.get("foreign_session_id") or not foreign and imported.get("path") == origin["path"]:
            return sid
    return None
