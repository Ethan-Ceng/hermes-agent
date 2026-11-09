"""Task events written by orchestration after its primary transaction."""

from hermes_db.domains.kanban.postgres.queries import kanban as repo


def _append_event(store, task_id, kind, payload=None, *, run_id=None):
    with store.write() as conn:
        repo.event(conn, store, task_id, kind, payload, run_id)
