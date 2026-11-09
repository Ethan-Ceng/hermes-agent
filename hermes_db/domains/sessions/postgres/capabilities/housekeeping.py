"""Housekeeping entry points publish events and remove files after commit."""

from hermes_db.domains.sessions.postgres.operations import housekeeping
from hermes_db.domains.sessions.postgres.queries import retirement_housekeeping, sessions


class SessionHousekeeping:
    def session_is_empty(self, session_id):
        from sqlalchemy import select
        from hermes_db.tables.conversations import sessions as table
        with self._read() as conn:
            child = table.alias("child")
            has_child = select(child.c.id).where(child.c.store_id == self.scope.require_store_id(),
                child.c.parent_session_id == table.c.id).exists()
            return conn.scalar(select(table.c.id).where(table.c.store_id == self.scope.require_store_id(),
                table.c.id == session_id, table.c.title.is_(None), ~housekeeping._has_messages(self.scope), ~has_child)) is not None

    def prune_empty_ghost_sessions(self, sessions_dir=None):
        with self._write() as conn:
            ids = housekeeping.prune_ghosts(conn, self.scope)
        self._after_session_delete(ids, reason="ghost_prune", sessions_dir=sessions_dir)
        return len(ids)

    def delete_empty_sessions(self, sessions_dir=None):
        with self._write() as conn:
            ids = housekeeping.delete_empty(conn, self.scope)
        if ids:
            self._after_session_delete(ids, reason="empty_sweep", sessions_dir=sessions_dir)
        else:
            self.collect_retired_media()
        return len(ids)

    def delete_session_if_empty(self, session_id, sessions_dir=None):
        with self._write() as conn:
            deleted = housekeeping.delete_if_empty(conn, self.scope, session_id)
        if deleted:
            self._after_session_delete([session_id], reason="empty_sweep", sessions_dir=sessions_dir)
        else:
            self.collect_retired_media()
        return deleted

    def discard_unadmitted_session(self, session_id):
        with self._write() as conn:
            deleted, fenced = housekeeping.discard_unadmitted(conn, self.scope, session_id)
        if fenced:
            self._after_session_delete(fenced, primary=session_id)
        return deleted

    def prune_never_active_keyed_sessions(self, *, older_than_days, sessions_dir=None, deleted_ids=None):
        with self._write() as conn:
            count, removed, skipped, routes, reported = housekeeping.never_active(conn, self.scope, older_than_days)
        if removed:
            self._after_session_delete(removed, sessions_dir=sessions_dir)
        if deleted_ids is not None:
            deleted_ids.extend(reported)
        return count, routes, len(skipped)

    def prune_retired_tombstones(self, older_than=604800):
        with self._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            retirement_housekeeping.prune(conn, self.scope, older_than)

    def retired_session(self, session_id):
        with self._read() as conn:
            return sessions.retired_session(conn, self.scope, session_id)

    def create_conflict(self, session_id):
        with self._read() as conn:
            if sessions.raw_session(conn, self.scope, session_id) is not None:
                return "session_exists", "Session already exists"
            if sessions.retired_session(conn, self.scope, session_id):
                return "session_deleted", "Session was deleted; its id cannot be reused"
        return None

    def has_mutation_receipt(self, principal_id, session_id, request_id):
        with self._read() as conn:
            return retirement_housekeeping.has_receipt(conn, self.scope, principal_id, session_id, request_id)

    def first_generation(self, derive, *, pinned=None, spent=None):
        from hermes_db.operations.effects import invoke
        generation = 0
        with self._profile.activate(), self._read() as conn:
            while True:
                sid = derive(generation)
                if sessions.retired_session(conn, self.scope, sid):
                    if invoke(pinned, conn, self.scope, sid):
                        return generation, sid
                elif spent is None or not invoke(spent, conn, self.scope, sid):
                    return generation, sid
                generation += 1

    def keep_passed_fences(self, derive, session_id):
        with self._profile.activate(), self._write() as conn:
            sessions.lock_store(conn, self.scope, exclusive=True)
            return retirement_housekeeping.keep_passed(conn, self.scope, derive, session_id)
