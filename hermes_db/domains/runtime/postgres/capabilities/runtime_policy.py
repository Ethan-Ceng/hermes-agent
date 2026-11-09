"""Owner deferred-pick persistence; mutation resolution remains at the edge."""

from hermes_db.domains.runtime.postgres.operations import deferred_pick


class RuntimePolicy:
    def defer_pick(self, **kwargs):
        with self._write() as conn:
            return deferred_pick.defer(conn, self.scope, **kwargs)

    def compare_deferred_pick(self, **kwargs):
        with self._write() as conn:
            return deferred_pick.compare(conn, self.scope, **kwargs)
