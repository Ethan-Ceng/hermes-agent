"""Task creation validates outside transactions; a Board fence owns idempotency."""

import json
import time
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from hermes_db.repositories import kanban as repo
from hermes_db.repositories import kanban_workspaces as workspaces
from hermes_db.tables.kanban import tasks
from hermes_db.core.values import encode_text, decode_text


def _workspace(store, fields):
    from hermes_cli import kanban_db as kb
    kind = fields.get("workspace_kind")
    project_id = fields.get("project_id")
    meta = kb.read_board_metadata(store.slug)
    if project_id is None and kind != "scratch":
        project_id = (meta.get("project_id") or "").strip() or None
    if kind is None:
        kind = "scratch"
    if kind not in kb.VALID_WORKSPACE_KINDS:
        raise ValueError(f"workspace_kind must be one of {sorted(kb.VALID_WORKSPACE_KINDS)}, got {kind!r}")
    branch = str(fields["branch_name"]).strip() or None if fields.get("branch_name") is not None else None
    if branch and kind != "worktree":
        raise ValueError("branch_name is only valid for worktree workspaces")
    project_id, project, project_repo, kind = kb._resolve_project_link(store, project_id,
        fields.get("project_source_task_id"), kind, fields.get("workspace_path"))
    path = fields.get("workspace_path")
    if path is None and project_repo is None and kind in {"dir", "worktree"}:
        path = meta.get("default_workdir") or None
    return dict(project_id=project_id, workspace_kind=kind, workspace_path=path, branch_name=branch), project, project_repo


def prepare(store, fields):
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_pr_acceptance import validate_contract
    title = fields["title"]
    if not title or not title.strip():
        raise ValueError("title is required")
    if fields.get("board") is not None and kb._require_slug(fields["board"]) != store.slug:
        raise ValueError("task Board must match its acquired Board resource")
    initial = fields.get("initial_status", "running")
    if initial not in kb.VALID_INITIAL_STATUSES:
        raise ValueError(f"initial_status must be one of {sorted(kb.VALID_INITIAL_STATUSES)}")
    model, provider = kb._validate_model_override(fields.get("model_override"), fields.get("provider_override"))
    skills = kb._normalize_task_skills(fields.get("skills"))
    values = {name: fields.get(name) for name in ("body", "created_by", "tenant", "session_id", "idempotency_key")}
    values.update(title=title.strip(), assignee=kb._canonical_assignee(fields.get("assignee")),
        priority=fields.get("priority", 0), model_override=model, provider_override=provider,
        reasoning_effort=kb.normalize_reasoning_effort(fields.get("reasoning_effort")),
        skills=json.dumps(skills) if skills is not None else None, goal_mode=int(bool(fields.get("goal_mode"))),
        completion_contract=validate_contract(fields.get("completion_contract")))
    values.update({name: kb._opt_int(fields.get(name)) for name in ("max_runtime_seconds", "max_retries", "goal_max_turns")})
    workspace, project, project_repo = _workspace(store, fields)
    values.update(workspace)
    path_keys = (workspaces.canonical_path(workspace["workspace_path"]),
                 workspaces.canonical_path(Path(project_repo) / ".worktrees") if project_repo is not None else None)
    return values, project, project_repo, path_keys


def _initial_state(conn, store, parents, fields, values):
    rows = {pid: repo.get(conn, store, pid) for pid in parents}
    missing = [pid for pid, row in rows.items() if row is None]
    if missing:
        raise ValueError(f"unknown parent task(s): {', '.join(missing)}")
    if values["tenant"] is None:
        values["tenant"] = next((row["tenant"] for row in rows.values() if row["tenant"]), None)
    if fields.get("initial_status") == "blocked":
        return "blocked", rows
    if fields.get("triage"):
        return "triage", rows
    return ("todo" if any(row["status"] != "done" for row in rows.values()) else "ready"), rows


def _insert(conn, store, values, project, project_repo, path_keys):
    from hermes_cli import kanban_db as kb
    for _attempt in range(2):
        task_id = kb._new_task_id()
        candidate = dict(values, id=task_id)
        path_key = path_keys[0]
        if project is not None and values["workspace_kind"] == "worktree":
            if project_repo is not None:
                candidate["workspace_path"] = str(Path(project_repo) / ".worktrees" / task_id)
                path_key = str(Path(path_keys[1]) / task_id)
            candidate["branch_name"] = candidate["branch_name"] or kb._project_branch_name(project, task_id, values["title"])
        inserted = conn.scalar(insert(tasks).values(**repo.owner(store), **repo.encode_task(candidate))
            .on_conflict_do_nothing(index_elements=[tasks.c.store_id, tasks.c.board_id, tasks.c.id]).returning(tasks.c.id))
        if inserted is not None:
            workspaces.register(conn, store, task_id, path_key)
            return task_id, candidate
    raise ValueError("could not allocate a unique Kanban task ID")


def insert_prepared(conn, store, fields, values, project, project_repo, path_keys):
    parents = tuple(pid for pid in fields.get("parents", ()) if pid)
    values = dict(values, created_at=int(time.time()))
    values["status"], parent_rows = _initial_state(conn, store, parents, fields, values)
    creator = fields.get("creator_task_id")
    if creator and values["session_id"] is None:
        origin = repo.get(conn, store, creator)
        values["session_id"] = origin["session_id"] if origin else None
    task_id, values = _insert(conn, store, values, project, project_repo, path_keys)
    for pid in parents:
        repo.link(conn, store, pid, task_id)
    payload = {name: values.get(name) for name in ("assignee", "status", "tenant", "workspace_kind", "workspace_path",
               "branch_name", "project_id", "model_override", "provider_override")}
    payload.update(parents=list(parents), creator_task_id=creator,
                   skills=json.loads(values["skills"]) if values["skills"] else None,
                   goal_mode=bool(values["goal_mode"]) or None)
    repo.event(conn, store, task_id, "created", payload)
    if values["status"] == "blocked":
        repo.event(conn, store, task_id, "blocked", {"reason": "initial_status", "status": "blocked", "actor": values["created_by"] or "user"})
    gating = [pid for pid, row in parent_rows.items() if row["status"] not in {"done", "archived"}]
    if values["status"] == "todo" and gating:
        repo.event(conn, store, task_id, "dependency_wait", {"reason": "parent_not_done", "parent": gating[0]})
    from hermes_db.operations.kanban_notify import inherit
    inherit(conn, store, task_id, [creator] if creator else (), created_at=values["created_at"])
    inherit(conn, store, task_id, parents, created_at=values["created_at"])
    return task_id


def create_task(store, **fields):
    values, project, project_repo, path_keys = prepare(store, fields)
    # Materialize caller iterators once; retries do not consume a different graph.
    fields["parents"] = tuple(fields.get("parents", ()))
    with store.write() as conn:
        idempotency = fields.get("idempotency_key")
        if idempotency:
            existing = conn.scalar(select(tasks.c.id).where(repo.scope(tasks, store),
                tasks.c.idempotency_key == encode_text(idempotency), tasks.c.status != b"archived")
                .order_by(tasks.c.created_at.desc(), tasks.c.id.desc()).limit(1))
            if existing is not None:
                return store.command_result(conn, decode_text(existing))
        return store.command_result(conn, insert_prepared(conn, store, fields, values, project, project_repo, path_keys))
