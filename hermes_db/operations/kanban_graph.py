"""Board-fenced DAG changes and atomic triage decomposition."""

import time
from sqlalchemy import delete, select

from hermes_db.repositories import kanban as repo
from hermes_db.tables.kanban import tasks, links
from hermes_db.core.values import encode_text


def parent_ids(store, task_id):
    with store.read() as conn:
        return repo.linked_ids(conn, store, task_id, parents=True)


def child_ids(store, task_id):
    with store.read() as conn:
        return repo.linked_ids(conn, store, task_id, parents=False)


def _unsatisfied(conn, store, task_id):
    rows = [repo.require_task(conn, store, pid) for pid in repo.linked_ids(conn, store, task_id, parents=True)]
    return [(row["id"], row["status"]) for row in rows if row["status"] not in {"done", "archived"}]


def unsatisfied_parents(store, task_id):
    with store.read() as conn:
        return _unsatisfied(conn, store, task_id)


def _would_cycle(conn, store, parent_id, child_id):
    seen, stack = set(), [child_id]
    while stack:
        node = stack.pop()
        if node == parent_id:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(repo.linked_ids(conn, store, node, parents=False))
    return False


def link_tasks(store, parent_id, child_id, *, expected_child_run_id=None):
    if parent_id == child_id:
        raise ValueError("a task cannot depend on itself")
    with store.write() as conn:
        rows = {tid: repo.get(conn, store, tid) for tid in (parent_id, child_id)}
        missing = [tid for tid, row in rows.items() if row is None]
        if missing:
            raise ValueError(f"unknown task(s): {', '.join(missing)}")
        child, parent = rows[child_id], rows[parent_id]
        if child["status"] == "running" and (expected_child_run_id is None or child["current_run_id"] != expected_child_run_id):
            raise ValueError(f"cannot link {parent_id} -> {child_id}: child is already running")
        if _would_cycle(conn, store, parent_id, child_id):
            raise ValueError(f"linking {parent_id} -> {child_id} would create a cycle")
        repo.link(conn, store, parent_id, child_id)
        gated = child["status"] == "ready" and parent["status"] not in {"done", "archived"}
        if gated:
            repo.task_update(conn, store, child_id, status="todo")
            repo.event(conn, store, child_id, "dependency_wait", {"reason": "parent_not_done", "demoted": True, "parent": parent_id})
        repo.event(conn, store, child_id, "linked", {"parent": parent_id, "child": child_id})
        from hermes_db.operations.kanban_notify import inherit
        inherit(conn, store, child_id, (parent_id,))
        return store.command_result(conn, gated)


def unlink_tasks(store, parent_id, child_id):
    with store.write() as conn:
        removed = conn.execute(delete(links).where(repo.scope(links, store),
            links.c.parent_id == encode_text(parent_id), links.c.child_id == encode_text(child_id))).rowcount > 0
        if removed:
            repo.event(conn, store, child_id, "unlinked", {"parent": parent_id, "child": child_id})
    if removed:
        recompute_ready(store)
    return removed


def task_graph_contexts(store, task_ids):
    ids = list(dict.fromkeys(str(task_id) for task_id in task_ids if task_id))
    contexts = {task_id: {"parents": [], "children": []} for task_id in ids}
    with store.read() as conn:
        for task_id in ids:
            for bucket, parents in (("parents", True), ("children", False)):
                for linked in repo.linked_ids(conn, store, task_id, parents=parents):
                    row = repo.require_task(conn, store, linked)
                    contexts[task_id][bucket].append({key: row[key] for key in ("id", "title", "status")})
    return contexts


def task_graph_context(store, task_id):
    return task_graph_contexts(store, [task_id])[task_id]


def _promote(conn, store, row, failure_limit):
    task_id = row["id"]
    history = repo.history(conn, store, task_id)
    if row["status"] == "blocked":
        limit = int(row["max_retries"]) if row["max_retries"] is not None else int(failure_limit)
        if repo.blocked_is_sticky(history) or int(row["consecutive_failures"] or 0) >= limit:
            return False
    if _unsatisfied(conn, store, task_id):
        return False
    status = repo.resume_status(history)
    repo.task_update(conn, store, task_id, status=status)
    repo.event(conn, store, task_id, "promoted", {"status": status} if status != "ready" else None)
    return True


def recompute_ready(store, failure_limit=None):
    from hermes_cli.kanban_db import DEFAULT_FAILURE_LIMIT
    limit = DEFAULT_FAILURE_LIMIT if failure_limit is None else failure_limit
    with store.write() as conn:
        rows = conn.execute(select(tasks).where(repo.scope(tasks, store), tasks.c.status.in_([b"todo", b"blocked"]))).mappings().all()
        return store.command_result(conn, sum(_promote(conn, store, repo.decode_task(row), limit) for row in rows))


def specify_triage_task(store, task_id, *, title=None, body=None, assignee=None, author=None):
    from hermes_cli.kanban_db import _canonical_assignee
    if title is not None and not title.strip():
        raise ValueError("title cannot be blank")
    assignee = _canonical_assignee(assignee)
    with store.write() as conn:
        row = repo.get(conn, store, task_id)
        if row is None or row["status"] != "triage":
            return False
        changed = {}
        for key, value in (("title", title.strip() if title is not None else None), ("body", body), ("assignee", assignee)):
            if value is not None and value != (row[key] or (None if key == "assignee" else "")):
                changed[key] = value
        repo.task_update(conn, store, task_id, status="todo", **changed)
        if changed and author and author.strip():
            repo.comment(conn, store, task_id, author.strip(),
                         "Specified — updated " + ", ".join(changed) + " and promoted to todo.", int(time.time()))
        repo.event(conn, store, task_id, "specified", {"changed_fields": list(changed)} if changed else None)
    recompute_ready(store)
    return True


def _decomposed_child(conn, store, root, child, author, now, path_key):
    from hermes_cli import kanban_db as kb
    from hermes_db.repositories import kanban_workspaces as workspaces
    root_kind = root["workspace_kind"] or "scratch"
    kind = child.get("workspace_kind") or root_kind
    path = child.get("workspace_path")
    if not path:
        path = root["workspace_path"] if kind == root_kind and kind != "worktree" else None
        path_key = workspaces.key_for_task(conn, store, root["id"]) if path else None
    body = child.get("body")
    task_id = kb._new_task_id()
    values = dict(id=task_id, title=child["title"].strip(), body=body if isinstance(body, str) else None,
        assignee=kb._canonical_assignee(child.get("assignee")), status="todo", workspace_kind=kind, workspace_path=path,
        tenant=root["tenant"], created_at=now, created_by=author or "decomposer", session_id=root["session_id"])
    conn.execute(tasks.insert().values(**repo.owner(store), **repo.encode_task(values)))
    workspaces.register(conn, store, task_id, path_key)
    repo.event(conn, store, task_id, "created", {"by": author or "decomposer", "from_decompose_of": root["id"]})
    from hermes_db.operations.kanban_notify import inherit
    inherit(conn, store, task_id, (root["id"],), created_at=now)
    return task_id


def decompose_triage_task(store, task_id, *, root_assignee, children, author=None, auto_promote=True):
    from hermes_cli.kanban_db import _canonical_assignee
    from hermes_cli.kanban_db_graph import _validate_children_graph
    if not children:
        return None
    root_assignee = _canonical_assignee(root_assignee)
    _validate_children_graph(children)
    from hermes_db.repositories.kanban_workspaces import canonical_path
    path_keys = [canonical_path(child.get("workspace_path")) for child in children]
    with store.write() as conn:
        root = repo.get(conn, store, task_id)
        if root is None or root["status"] != "triage" or any(row["kind"] == "decomposed" for row in repo.history(conn, store, task_id)):
            return None
        now = int(time.time())
        ids = [_decomposed_child(conn, store, root, child, author, now, path_keys[index]) for index, child in enumerate(children)]
        for idx, child in enumerate(children):
            for parent_idx in child.get("parents") or []:
                repo.link(conn, store, ids[parent_idx], ids[idx])
                repo.event(conn, store, ids[idx], "linked", {"parent": ids[parent_idx], "child": ids[idx]})
        for child_id in ids:
            repo.link(conn, store, child_id, task_id)
        values = {"status": "todo"}
        if root_assignee is not None:
            values["assignee"] = root_assignee
        repo.task_update(conn, store, task_id, **values)
        if author and author.strip():
            repo.comment(conn, store, task_id, author.strip(),
                "Decomposed into " + ", ".join(ids) + ". Root will wake when all children complete.", now)
        repo.event(conn, store, task_id, "decomposed", {"child_ids": ids, "root_assignee": root_assignee})
    if auto_promote:
        recompute_ready(store)
    return ids
