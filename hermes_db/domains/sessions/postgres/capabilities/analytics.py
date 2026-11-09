"""Explicit analytics capabilities shared by terminal, Web and Desktop readers."""

from hermes_db.domains.sessions.postgres.queries import analytics, insights


class SessionAnalytics:
    def insights_rows(self, kind, cutoff, source=None):
        self.flush_for_read()
        with self._read() as conn:
            return insights.rows(conn, self.scope, kind, cutoff, source)

    def analytics_rows(self, kind, cutoff):
        self.flush_for_read()
        with self._read() as conn:
            return analytics.rows(conn, self.scope, kind, cutoff)
