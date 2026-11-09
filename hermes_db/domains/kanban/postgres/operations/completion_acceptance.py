"""PR acceptance runs off-connection and binds to the same task/run/assignee snapshot."""

from hermes_db.domains.kanban.postgres.queries import kanban as repo


def snapshot(task):
    return tuple(task[key] for key in ("current_run_id", "status", "completion_contract", "assignee"))


def prepare(store, task, expected_run_id, metadata):
    from hermes_cli import kanban_pr_acceptance as acceptance
    contract = task["completion_contract"]
    if not contract or contract == "local-only":
        return None
    if expected_run_id is not None and task["current_run_id"] != expected_run_id:
        return False
    published_pr = metadata.get("published_pr") if isinstance(metadata, dict) else None
    match = acceptance._PR.fullmatch(published_pr) if isinstance(published_pr, str) else None
    captured = snapshot(task)
    if match and contract == match[1]:
        with store.write() as conn:
            current = repo.get(conn, store, task["id"])
            if current is None or snapshot(current) != captured:
                return False
            repo.task_update(conn, store, task["id"], completion_contract=published_pr)
        task["completion_contract"] = contract = published_pr
        captured = snapshot(task)
    receipt = acceptance.collect_acceptance(contract, published_pr, assignee=task["assignee"])
    return captured, receipt


def record(conn, store, task, prepared):
    if prepared is None:
        return True
    captured, receipt = prepared
    if snapshot(task) != captured:
        return False
    repo.event(conn, store, task["id"], "pr_acceptance", receipt, task["current_run_id"])
    if not receipt["ok"]:
        detail = f"PR acceptance {receipt['classification']}: {receipt.get('detail', '')} {receipt['recovery']}"
        repo.task_update(conn, store, task["id"], last_failure_error=detail)
    return receipt["ok"]
