"""Lease and live capacity are checked inside the claim's Board transaction."""

from dataclasses import dataclass, replace
import time

from sqlalchemy import func, select

from hermes_db.errors import StorageConfigurationError
from hermes_db.domains.kanban.postgres.queries import kanban as repo, runs as run_repo
from hermes_db.tables.kanban import tasks
from hermes_db.core.values import encode_text


@dataclass(frozen=True)
class DispatchPermit:
    lease: object
    max_spawn: int | None
    max_in_progress: int | None
    per_profile_cap: int | None = None
    assignee: str | None = None

    def for_assignee(self, assignee, cap):
        return replace(self, assignee=assignee, per_profile_cap=cap)

    def admit(self, conn, store, task):
        if self.lease.store.scope != store.scope:
            raise StorageConfigurationError("Dispatch lease belongs to another Profile store")
        self.lease.validate(conn, lock=True)
        if task["assignee"] != self.assignee:
            return False
        counts = select(func.count()).select_from(tasks).where(tasks.c.store_id == store.scope.require_store_id(),
                                                              tasks.c.status == b"running")
        if self.max_in_progress is not None and conn.scalar(counts) >= self.max_in_progress:
            return False
        board_counts = counts.where(tasks.c.board_id == store.board_id)
        if self.max_spawn is not None and conn.scalar(board_counts) >= self.max_spawn:
            return False
        if self.per_profile_cap is not None:
            return conn.scalar(board_counts.where(tasks.c.assignee == encode_text(self.assignee))) < self.per_profile_cap
        return True

    def before_spawn(self, store, claimed, ttl_seconds):
        from hermes_cli import kanban_db as kb
        with store.write() as conn:
            self.lease.validate(conn, lock=True)
            task = repo.get(conn, store, claimed.id)
            if (task is None or task["status"] != "running" or task["current_run_id"] != claimed.current_run_id
                    or task["claim_lock"] != claimed.claim_lock):
                return False
            expires = int(time.time()) + kb._resolve_claim_ttl_seconds(ttl_seconds)
            repo.task_update(conn, store, claimed.id, claim_expires=expires)
            run_repo.update_run(conn, store, claimed.current_run_id, claim_expires=expires)
        return True
