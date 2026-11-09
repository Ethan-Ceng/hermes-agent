"""Detached Kanban task CRUD, exact text and atomic field changes."""

import time
from sqlalchemy import delete, func, select

from hermes_db.domains.kanban.postgres.queries import kanban as repo
from hermes_db.tables.kanban import tasks, comments, events
from hermes_db.core.values import decode_text, encode_text

from hermes_db.domains.kanban.postgres.operations.create import create_task


def get_task(store, task_id):
    from hermes_cli.kanban_db import Task
    with store.read() as conn:
        row = repo.get(conn, store, task_id)
        return Task.from_row(row) if row is not None else None


def _sort(order_by):
    from hermes_cli.kanban_db import VALID_SORT_ORDERS
    orders = {
        "created": (tasks.c.created_at.asc(), tasks.c.id.asc()),
        "created-desc": (tasks.c.created_at.desc(), tasks.c.id.desc()),
        "priority": (tasks.c.priority.desc(), tasks.c.created_at.asc()),
        "priority-desc": (tasks.c.priority.asc(), tasks.c.created_at.asc()),
        "status": (tasks.c.status.asc(), tasks.c.created_at.asc()),
        "assignee": (tasks.c.assignee.asc().nulls_first(), tasks.c.created_at.asc()),
        "title": (tasks.c.title.asc(), tasks.c.id.asc()),
        "updated": (tasks.c.started_at.desc().nulls_last(), tasks.c.created_at.desc()),
        "completed-desc": (tasks.c.completed_at.desc().nulls_last(), tasks.c.id.desc()),
    }
    name = order_by.strip().lower() if order_by is not None else "priority"
    if name not in orders:
        raise ValueError(f"order_by must be one of {sorted(VALID_SORT_ORDERS)}")
    return orders[name]


def list_tasks(store, *, assignee=None, status=None, tenant=None, session_id=None, include_archived=False,
               limit=None, order_by=None, workflow_template_id=None, current_step_key=None):
    from hermes_cli.kanban_db import Task, VALID_STATUSES, _canonical_assignee
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
    query = select(tasks).where(repo.scope(tasks, store))
    for name, value in (("assignee", _canonical_assignee(assignee)), ("status", status), ("tenant", tenant),
                        ("session_id", session_id), ("workflow_template_id", workflow_template_id), ("current_step_key", current_step_key)):
        if value is not None:
            query = query.where(tasks.c[name] == encode_text(value))
    if not include_archived and status != "archived":
        query = query.where(tasks.c.status != b"archived")
    if limit and int(limit) >= 0:
        query = query.limit(int(limit))
    with store.read() as conn:
        return [Task.from_row(repo.decode_task(row)) for row in conn.execute(query.order_by(*_sort(order_by))).mappings()]


def notify_task_updated(store, task_id, changed_fields, *, board=None):
    from hermes_cli import kanban_db as kb
    if kb._kanban_observer_consumed("on_kanban_task_updated"):
        task = get_task(store, task_id)
        kb._fire_kanban_lifecycle_hook("on_kanban_task_updated", task_id, board=board or store.slug,
            assignee=task.assignee if task else None, run_id=task.current_run_id if task else None, changed_fields=list(changed_fields))


def assign_task(store, task_id, profile):
    from hermes_cli import kanban_db as kb
    profile = kb._canonical_assignee(profile)
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None:
            return False
        if row["claim_lock"] is not None and row["status"] == "running":
            from hermes_cli.kanban_errors import TaskAlreadyClaimedError
            raise TaskAlreadyClaimedError(f"cannot reassign {task_id}: currently running (claimed). Wait for completion or reclaim the stale lock first.")
        values = {"assignee": profile}
        if row["assignee"] != profile:
            values.update(consecutive_failures=0, last_failure_error=None)
        repo.task_update(conn, store, task_id, **values)
        repo.event(conn, store, task_id, "assigned", {"assignee": profile, "from": row["assignee"]})
    kb.notify_task_updated(store, task_id, ("assignee",))
    return True


def _override(store, task_id, values, kind, payload, archived_msg):
    from hermes_cli import kanban_db as kb
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None:
            return False
        if row["status"] == "archived":
            raise RuntimeError(f"{archived_msg} on archived task {task_id}")
        repo.task_update(conn, store, task_id, **values)
        repo.event(conn, store, task_id, kind, payload)
    kb.notify_task_updated(store, task_id, tuple(values))
    return True


def set_model_override(store, task_id, model, provider=None):
    from hermes_cli.kanban_db import _validate_model_override
    model, provider = _validate_model_override(model, provider)
    return _override(store, task_id, {"model_override": model, "provider_override": provider}, "model_override_set",
                     {"model": model, "provider": provider}, "cannot set model override")


def set_reasoning_effort(store, task_id, effort):
    from hermes_cli.kanban_db import normalize_reasoning_effort
    effort = normalize_reasoning_effort(effort)
    return _override(store, task_id, {"reasoning_effort": effort}, "reasoning_effort_set", {"reasoning_effort": effort}, "cannot set reasoning effort")


def edit_task(store, task_id, *, title=None, body=None, priority=None, result=None, summary=None, metadata=None, board=None):
    from hermes_cli import kanban_db as kb
    if result is not None:
        from hermes_db.domains.kanban.postgres.operations.result_edit import edit_result
        return edit_result(store, task_id, title=title, body=body, priority=priority, result=result,
                           summary=summary, metadata=metadata, board=board)
    values = {name: value for name, value in (("title", title), ("body", body), ("priority", priority)) if value is not None}
    if not values:
        return False
    with store.write() as conn:
        if repo.get(conn, store, task_id) is None:
            return False
        repo.task_update(conn, store, task_id, **values)
        if priority is not None:
            repo.event(conn, store, task_id, "reprioritized", {"priority": priority})
        changed = [name for name in values if name != "priority"]
        if changed:
            repo.event(conn, store, task_id, "edited", {"fields": changed})
    kb.notify_task_updated(store, task_id, list(values), board=board)
    return True


def add_comment(store, task_id, author, body):
    if not body or not body.strip():
        raise ValueError("comment body is required")
    if not author or not author.strip():
        raise ValueError("comment author is required")
    with store.write() as conn:
        repo.require_task(conn, store, task_id)
        comment_id = repo.comment(conn, store, task_id, author.strip(), body.strip(), int(time.time()))
        repo.event(conn, store, task_id, "commented", {"author": author, "len": len(body)})
        return store.command_result(conn, comment_id)


def list_comments(store, task_id):
    from hermes_cli.kanban_db import Comment
    with store.read() as conn:
        return [Comment.from_row(repo.decode_record(row)) for row in conn.execute(select(comments).where(repo.key(store, task_id, comments))
                .order_by(comments.c.created_at, comments.c.id)).mappings()]


def list_comments_after(store, task_id, *, after_id=0):
    from hermes_cli.kanban_db import Comment
    with store.read() as conn:
        return [Comment.from_row(repo.decode_record(row)) for row in conn.execute(select(comments).where(repo.key(store, task_id, comments),
                comments.c.id > int(after_id)).order_by(comments.c.id)).mappings()]


def list_events(store, task_id):
    from hermes_cli.kanban_db import Event
    with store.read() as conn:
        return [Event.from_row(repo.decode_record(row)) for row in conn.execute(select(events).where(repo.key(store, task_id, events))
                .order_by(events.c.created_at, events.c.id)).mappings()]


def _delete(store, task_id, *, archived_only):
    from hermes_db.domains.kanban.postgres.operations.graph import recompute_ready
    from hermes_db.tables.kanban_notify import subscriptions
    with store.write() as conn:
        condition = repo.key(store, task_id)
        if archived_only:
            condition = condition & (tasks.c.status == b"archived")
        count = conn.execute(delete(tasks).where(condition)).rowcount
        if count:
            conn.execute(delete(subscriptions).where(repo.key(store, task_id, subscriptions)))
    if count and not archived_only:
        recompute_ready(store)
    return count > 0


def delete_task(store, task_id):
    return _delete(store, task_id, archived_only=False)


def delete_archived_task(store, task_id):
    return _delete(store, task_id, archived_only=True)


def board_stats(store):
    with store.read() as conn:
        rows = conn.execute(select(tasks.c.status, tasks.c.assignee, func.count().label("n"))
            .where(repo.scope(tasks, store), tasks.c.status != b"archived").group_by(tasks.c.status, tasks.c.assignee)).all()
        oldest = conn.scalar(select(func.min(tasks.c.created_at)).where(repo.scope(tasks, store), tasks.c.status == b"ready"))
    by_status, by_assignee = {}, {}
    for status, assignee, count in rows:
        status, assignee = decode_text(status), decode_text(assignee)
        by_status[status] = by_status.get(status, 0) + count
        if assignee is not None:
            by_assignee.setdefault(assignee, {})[status] = count
    now = int(time.time())
    return dict(by_status=by_status, by_assignee=by_assignee, oldest_ready_age_seconds=now - oldest if oldest is not None else None, now=now)


def known_assignees(store):
    from hermes_cli.kanban_db import list_profiles_on_disk
    on_disk = set(list_profiles_on_disk())
    counts = board_stats(store)["by_assignee"]
    return [{"name": name, "on_disk": name in on_disk, "counts": counts.get(name, {})} for name in sorted(on_disk | set(counts))]


def gc_events(store, *, older_than_seconds=30 * 24 * 3600):
    from hermes_cli.kanban_db import _retention_seconds
    cutoff = int(time.time()) - _retention_seconds(older_than_seconds)
    with store.write() as conn:
        terminal = select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.status.in_([b"done", b"archived"]))
        return conn.execute(delete(events).where(repo.scope(events, store), events.c.created_at < cutoff,
            events.c.kind != b"decomposed", events.c.task_id.in_(terminal))).rowcount
