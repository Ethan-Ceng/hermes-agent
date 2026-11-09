"""One Board transaction commits the swarm topology, blackboard and root activation."""

import json
import time
from sqlalchemy import select

from hermes_cli import kanban_swarm as swarm
from hermes_cli.kanban_swarm_plan import plan_swarm
from hermes_db.operations import kanban_create as create
from hermes_db.repositories import kanban as repo, kanban_runs as run_repo
from hermes_db.tables.kanban import tasks, comments
from hermes_db.core.values import decode_text, encode_text


def _blackboard(conn, store, root):
    from hermes_cli.kanban_db import Comment
    rows = conn.execute(select(comments).where(repo.key(store, root, comments)).order_by(comments.c.created_at, comments.c.id)).mappings()
    return swarm.merge_blackboard(Comment.from_row(repo.decode_record(row)) for row in rows)


def _insert(conn, store, prepared, *, parents=None, suffix=""):
    fields, (values, project, project_repo, path_keys) = prepared
    values = dict(values)
    fields = dict(fields, parents=parents or ())
    if suffix:
        values["body"] = (values["body"] or "") + suffix
    return create.insert_prepared(conn, store, fields, values, project, project_repo, path_keys)


def _root(conn, store, prepared):
    idempotency = prepared[0].get("idempotency_key")
    if idempotency:
        found = conn.scalar(select(tasks.c.id).where(repo.scope(tasks, store), tasks.c.idempotency_key == encode_text(idempotency),
            tasks.c.status != b"archived").order_by(tasks.c.created_at.desc(), tasks.c.id.desc()).limit(1))
        if found is not None:
            return decode_text(found)
    return _insert(conn, store, prepared)


def _existing(conn, store, root):
    topology = _blackboard(conn, store, root).get("topology")
    if not isinstance(topology, dict):
        return None
    workers = [str(value) for value in topology.get("worker_ids", ()) if value]
    verifier, synthesizer = topology.get("verifier_id"), topology.get("synthesizer_id")
    return swarm.SwarmCreated(root, workers, str(verifier), str(synthesizer)) if workers and verifier and synthesizer else None


def _build(conn, store, plan, prepared):
    root = _root(conn, store, prepared["root"])
    created = _existing(conn, store, root)
    if created is None:
        suffix = swarm._swarm_context(root, plan["goal"])
        workers = [_insert(conn, store, item, parents=[root], suffix=suffix) for item in prepared["workers"]]
        verifier = _insert(conn, store, prepared["verifier"], parents=workers, suffix=suffix)
        synthesizer = _insert(conn, store, prepared["synthesizer"], parents=[verifier], suffix=suffix)
        created = swarm.SwarmCreated(root, workers, verifier, synthesizer)
        body = swarm.BLACKBOARD_PREFIX + json.dumps({"key": "topology", "value": created.as_dict() | {"goal": plan["goal"]}},
                                                   ensure_ascii=False, sort_keys=True)
        repo.comment(conn, store, root, plan["created_by"], body, int(time.time()))
        repo.event(conn, store, root, "commented", {"author": plan["created_by"], "len": len(body)})
    task = repo.require_task(conn, store, root)
    activated = task["status"] == "blocked"
    if activated:
        summary = "Swarm topology planned; root remains the shared blackboard."
        repo.task_update(conn, store, root, status="done", completed_at=int(time.time()),
                         claim_lock=None, claim_expires=None, worker_pid=None)
        run_id = run_repo.synthesize(conn, store, task, outcome="completed", summary=summary,
            metadata={"kind": "kanban_swarm_v1", "goal": plan["goal"], "worker_count": len(created.worker_ids)})
        repo.event(conn, store, root, "completed", {"result_len": 0, "summary": summary}, run_id)
    return created, activated


def create_swarm(store, **fields):
    from hermes_cli import kanban_db as kb
    plan = plan_swarm(**fields)
    def prepare(value):
        return value, create.prepare(store, value)
    prepared = {name: prepare(plan[name]) for name in ("root", "verifier", "synthesizer")}
    prepared["workers"] = [prepare(value) for value in plan["workers"]]
    with store.write() as conn:
        created, activated = _build(conn, store, plan, prepared)
    if activated:
        kb.recompute_ready(store)
        root, run = kb.get_task(store, created.root_id), kb.latest_run(store, created.root_id)
        kb._fire_kanban_lifecycle_hook("kanban_task_completed", created.root_id, board=store.slug,
            assignee=root.assignee, run_id=run.id, summary=run.summary)
    return created
