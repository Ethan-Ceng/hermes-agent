"""Public prune writes and backend-independent carrier-aware rewind planning."""

from copy import deepcopy

from agent.message_metadata import DB_ROW_SNAPSHOT
from hermes_db.domains.sessions.postgres.operations import rewrites
from hermes_state_rewind import SessionRewindMixin


class SessionRewrites:
    # These two algorithms use only public transcript reads/writes and pure
    # message projections; neither inherits a SQLite connection or SQL method.
    plan_user_turn_rewind = SessionRewindMixin.plan_user_turn_rewind
    rewind_user_turn = SessionRewindMixin.rewind_user_turn

    def retain_refused_turn_for_display(self, session_id, *, notice, boundary_row_id=None):
        from agent.context_compressor import split_user_originated_turn
        from agent.turn_failure_copy import CONTENT_REFUSED_DISPLAY_KIND, CONTENT_REFUSED_METADATA_KEY
        from hermes_db.domains.sessions.postgres.support.message_codec import codec
        from hermes_db.domains.sessions.postgres.operations.messages import rewind
        from hermes_db.domains.sessions.postgres.queries import messages as repo
        from hermes_db.tables.conversations import messages
        from hermes_state_rewind import RewindTargetUnavailableError
        # Capture the same active generation the planner judged, then validate under the root lock.
        with self._read() as conn:
            row = repo.one(conn, self.scope, session_id, boundary_row_id) if isinstance(boundary_row_id, int) and boundary_row_id > 0 else None
            if row and row['role'] == 'user' and row['active']:
                target = row['id']
                handoff, _ = split_user_originated_turn(codec._row_to_message_dict(row, warn_context='refusal', summary_flag=True))
                preserve = handoff is not None
                expected = repo.active_ids(conn, self.scope, session_id)
        if not row or row['role'] != 'user' or not row['active']:
            # The planner performs public reads; release this checkout before it runs (pool_size=1).
            try:
                plan = self.plan_user_turn_rewind(session_id, -1)
            except RewindTargetUnavailableError:
                return False
            target, preserve, expected = plan.target_row_id, plan.scaffold is not None, plan.expected_active_ids
        with self._write() as conn:
            rewind(conn, self.scope, session_id, target, preserve_compaction_handoff=preserve, expected_active_ids=expected)
            row = repo.one(conn, self.scope, session_id, target)
            metadata = codec._decode_display_metadata(row['display_metadata']) or {}
            metadata[CONTENT_REFUSED_METADATA_KEY] = {'notice': notice}
            repo.update_row(conn, self.scope, session_id, target, {'compacted': 1,
                'display_kind': CONTENT_REFUSED_DISPLAY_KIND, 'display_metadata': codec._encode_display_metadata(metadata)})
        return True

    def rewrite_pruned_rows(self, session_id, changes, *, model_config_patch=None, turn_lease_holder=None, turn_lease_ttl_seconds=300):
        work = deepcopy(changes)
        with self._write() as conn:
            count = rewrites.prune(conn, self.scope, session_id, work, model_config_patch=model_config_patch,
                turn_lease_holder=turn_lease_holder, turn_lease_ttl_seconds=turn_lease_ttl_seconds)
        for (_, replacement), (_, committed) in zip(changes, work):
            if DB_ROW_SNAPSHOT in committed:
                replacement[DB_ROW_SNAPSHOT] = committed[DB_ROW_SNAPSHOT]
        return count
