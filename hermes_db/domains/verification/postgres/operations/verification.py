"""Complete evidence operations with a store fence for sharing and retention."""

import json

from hermes_db.domains.verification.postgres.queries import verification as repo


def record(resource, evidence, created_at, *, cutoff, per_root_limit, total_limit):
    from agent.runtime_domain_store import WorkerDomainStore
    if isinstance(resource, WorkerDomainStore):
        # Retention and clock policy belong to the owner, not the compute producer.
        return resource.command('verification.record', {'evidence': evidence})
    with resource.write() as conn:
        repo.lock_store(conn, resource.scope)
        event_id = repo.save_event(conn, resource.scope, evidence, created_at)
        share = evidence["kind"] == "verify" and evidence["status"] == "passed" and evidence["scope"] == "full"
        repo.point_to_event(conn, resource.scope, evidence["session_id"], evidence["root"], event_id, share=share)
        repo.prune(conn, resource.scope, evidence["session_id"], evidence["root"], cutoff=cutoff,
                   per_root_limit=per_root_limit, total_limit=total_limit)
    return {"id": event_id, **evidence, "created_at": created_at}


def mark_edited(resource, session_id, root, changed, edited_at):
    from agent.runtime_domain_store import WorkerDomainStore
    if isinstance(resource, WorkerDomainStore):
        return resource.command('verification.mark_edited', dict(session_id=session_id, root=root, changed=changed))
    with resource.write() as conn:
        repo.lock_store(conn, resource.scope)
        repo.mark_edited(conn, resource.scope, session_id, root, changed, edited_at)
    return {"session_id": session_id, "root": root, "last_edit_at": edited_at, "changed_paths": changed}


def status(resource, session_id, root):
    from agent.runtime_domain_store import WorkerDomainStore
    if isinstance(resource, WorkerDomainStore):
        return resource.query('verification.status', dict(session_id=session_id, root=root))
    with resource.read() as conn:
        state = repo.state(conn, resource.scope, session_id, root)
        result = {"evidence": None, "root": root, "session_id": session_id, "changed_paths": []}
        if state is None:
            return {"status": "unverified", **result}
        result["changed_paths"] = json.loads(state["changed_paths_json"])
        event = repo.event(conn, resource.scope, state["last_event_id"]) if state["last_event_id"] is not None else None
        edited_at = state["last_edit_at"]
        stale = bool(event is not None and edited_at and edited_at > event["created_at"])
        if event is None or stale:
            shared = repo.shared_event(conn, resource.scope, root, edited_at)
            if shared is not None:
                event, stale = shared, False
        if event is None:
            return {"status": "unverified", **result}
        return {"status": "stale" if stale else event["status"], **result, "evidence": event}
