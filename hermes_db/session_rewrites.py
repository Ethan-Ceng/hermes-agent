"""Public prune writes and backend-independent carrier-aware rewind planning."""

from copy import deepcopy

from agent.message_metadata import DB_ROW_SNAPSHOT
from hermes_db.operations import rewrites
from hermes_state_rewind import SessionRewindMixin


class SessionRewrites:
    # These two algorithms use only public transcript reads/writes and pure
    # message projections; neither inherits a SQLite connection or SQL method.
    plan_user_turn_rewind = SessionRewindMixin.plan_user_turn_rewind
    rewind_user_turn = SessionRewindMixin.rewind_user_turn

    def rewrite_pruned_rows(self, session_id, changes, *, model_config_patch=None, turn_lease_holder=None, turn_lease_ttl_seconds=300):
        work = deepcopy(changes)
        with self._write() as conn:
            count = rewrites.prune(conn, self.scope, session_id, work, model_config_patch=model_config_patch,
                turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)
        for (_, replacement), (_, committed) in zip(changes, work):
            if DB_ROW_SNAPSHOT in committed:
                replacement[DB_ROW_SNAPSHOT] = committed[DB_ROW_SNAPSHOT]
        return count
