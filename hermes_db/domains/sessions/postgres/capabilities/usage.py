"""Usage methods preserve summary/route/task distinctions."""

import asyncio

from sqlalchemy import func, select

from hermes_db.domains.sessions.postgres.operations.sessions import create_on_connection
from hermes_db.domains.sessions.postgres.queries import sessions as repo, usage
from hermes_db.tables.conversations import session_model_usage, sessions


class SessionUsage:
    def update_token_counts(self, session_id, input_tokens=0, output_tokens=0, model=None, cache_read_tokens=0,
                            cache_write_tokens=0, reasoning_tokens=0, estimated_cost_usd=None, actual_cost_usd=None,
                            cost_status=None, cost_source=None, pricing_version=None, billing_provider=None,
                            billing_base_url=None, billing_mode=None, api_call_count=0, absolute=False, source=None, task=""):
        values = {name: value for name, value in locals().items() if name not in ("self", "session_id", "source")}
        with self._write() as conn:
            create_on_connection(conn, self.scope, session_id, source or "unknown", own_profile=self._own_profile, model=model)
            usage.update_totals(conn, self.scope, session_id, values)

    def record_auxiliary_usage(self, session_id, task, *, model=None, billing_provider=None, billing_base_url=None,
                               input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                               reasoning_tokens=0, estimated_cost_usd=None, api_call_count=1):
        if not session_id or not task:
            return
        values = {name: value for name, value in locals().items() if name not in ("self", "session_id", "task")}
        values["api_call_count"] = 1 if api_call_count is None else int(api_call_count)
        with self._write() as conn:
            create_on_connection(conn, self.scope, session_id, "unknown", own_profile=self._own_profile)
            usage.record_route(conn, self.scope, session_id, values, task=task)

    def update_session_billing_route(self, session_id, *, provider, base_url, billing_mode=None):
        self.flush_token_counts()
        with self._write() as conn:
            row = repo.lock_session(conn, self.scope, session_id)
            if row:
                repo.update_session(conn, self.scope, session_id, {"billing_provider": provider, "billing_base_url": base_url,
                    "billing_mode": billing_mode if billing_mode is not None else row["billing_mode"]})

    def get_recent_session_model_route(self, session_id):
        self.flush_for_read()
        with self._read() as conn:
            return usage.recent_route(conn, self.scope, session_id)

    def auxiliary_usage_by_task(self, session_id):
        names = (*usage.COUNTERS[:-1], "estimated_cost_usd")
        with self._read() as conn:
            ids = [row["id"] for row in repo.lineage_rows(conn, self.scope, session_id)]
            rows = conn.execute(select(session_model_usage.c.task,
                func.sum(session_model_usage.c.api_call_count).label("api_calls"),
                *(func.sum(session_model_usage.c[name]).label(name) for name in names))
                .where(session_model_usage.c.store_id == self.scope.require_store_id(), session_model_usage.c.session_id.in_(ids),
                       session_model_usage.c.task != "").group_by(session_model_usage.c.task)).mappings()
            return {row["task"]: {key: value for key, value in row.items() if key != "task"} for row in rows}

    def usage_totals(self, *, min_message_count=1, include_archived=False):
        with self._read() as conn:
            statement = select(func.coalesce(func.sum(func.coalesce(sessions.c.input_tokens, 0)
                + func.coalesce(sessions.c.output_tokens, 0)), 0).label("tokens"),
                func.coalesce(func.sum(func.coalesce(sessions.c.actual_cost_usd, sessions.c.estimated_cost_usd, 0)), 0).label("cost_usd"))
            statement = statement.where(sessions.c.store_id == self.scope.require_store_id(),
                sessions.c.parent_session_id.is_(None), sessions.c.message_count >= min_message_count)
            if not include_archived:
                statement = statement.where(sessions.c.archived == 0)
            return dict(conn.execute(statement).mappings().one())

    def queue_token_counts(self, session_id, **kwargs):
        self._assert_open()
        self._usage_writer.enqueue(session_id, kwargs)

    def flush_token_counts(self, timeout=5.0):
        return self._usage_writer.flush(timeout) if self._usage_writer is not None else True

    def flush_for_read(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self.flush_token_counts()
        return self.flush_token_counts(timeout=0.0)
