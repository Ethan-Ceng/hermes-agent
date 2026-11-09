"""Closed Board verbs and exact attempt fences for an authenticated adopted worker."""

import inspect

from hermes_state_runtime import RuntimeStoreError

READS = frozenset({"get_task", "get_run", "latest_run", "list_runs", "latest_summary", "latest_summaries",
    "list_tasks", "list_comments", "list_comments_after", "list_events", "list_attachments", "get_attachment",
    "parent_ids", "child_ids", "unsatisfied_parents", "task_graph_context", "board_stats", "goal_run_status",
    "recent_profile_completions", "_verify_created_cards", "worker.claim_live", "worker.submitter", "board.resolve",
    "list_notify_subs", "build_worker_context"})
COMMANDS = frozenset({"add_comment", "create_task", "complete_task", "block_task", "schedule_task", "request_review",
    "request_changes", "heartbeat_claim", "heartbeat_worker", "recompute_ready", "_record_task_failure", "link_tasks",
    "claim_task", "claim_review_task", "worker.bind", "worker.result", "unblock_task", "add_notify_sub",
    "store_attachment_bytes", "attachment.chunk", "attachment.commit"})
_LIFECYCLE = frozenset({"complete_task", "block_task", "schedule_task", "request_review", "request_changes",
                       "heartbeat_worker", "_record_task_failure"})


def _owner_operation(store, context, params, operation, payload):
    from hermes_db.domains.kanban.postgres.operations import owner
    if operation == "worker.bind":
        from hermes_cli.kanban_db_dispatch import _process_fingerprint, UNVERIFIED_WORKER_FINGERPRINT
        if payload:
            raise RuntimeStoreError("invalid_params")
        fingerprint = _process_fingerprint(params["pid"]) or UNVERIFIED_WORKER_FINGERPRINT
        return owner.bind_worker(store, context, pid=params["pid"], fingerprint=fingerprint)
    if operation == "worker.result":
        if (set(payload) != {"code", "last_output"} or type(payload["code"]) is not int
                or not isinstance(payload["last_output"], str) or len(payload["last_output"]) > 500):
            raise RuntimeStoreError("invalid_params")
        return owner.record_result(store, context, pid=params["pid"], code=payload["code"], last_output=payload["last_output"])
    if payload:
        raise RuntimeStoreError("invalid_params")
    if operation == "worker.claim_live":
        return owner.bound_claim_live(store, context, pid=params["pid"])
    from hermes_db.domains.kanban.postgres.queries import runs as kanban_runs
    with store.read() as conn:
        run = kanban_runs.get(conn, store, context["run_id"])
    return {key: run[key] for key in ("worker_pid", "worker_started_at")} if run else None


def invoke(store, context, params, operation, payload):
    from hermes_cli import kanban_db as kb, kanban_db_dispatch as dispatch
    from hermes_db.domains.kanban.routing.wire import unpack
    if operation.startswith("worker."):
        if "task_id" not in context:
            raise RuntimeStoreError("permission_denied")
        return _owner_operation(store, context, params, operation, payload)
    if set(payload) not in ({"args", "kwargs"}, {"args", "kwargs", "target"}):
        raise RuntimeStoreError("invalid_params")
    try:
        args, kwargs = unpack(payload["args"]), unpack(payload["kwargs"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeStoreError("invalid_params") from error
    if not isinstance(args, (list, tuple)) or not isinstance(kwargs, dict):
        raise RuntimeStoreError("invalid_params")
    if operation == "attachment.commit":
        from gateway.session_worker_kanban_upload import commit_upload
        return commit_upload(store, context, params, context["principal"], args, kwargs)
    from hermes_cli import kanban_db_notify as notify
    handlers = {"heartbeat_worker": dispatch.heartbeat_worker, "add_notify_sub": notify.add_notify_sub,
                "list_notify_subs": notify.list_notify_subs}
    handler = handlers[operation] if operation in handlers else getattr(kb, operation)
    try:
        bound = inspect.signature(handler).bind(store, *args, **kwargs)
    except TypeError as error:
        raise RuntimeStoreError("invalid_params") from error
    target = bound.arguments.get("task_id")
    owned = "task_id" in context
    if owned and operation == "unblock_task":
        raise RuntimeStoreError("permission_denied")
    if owned and (operation in _LIFECYCLE or operation in {"claim_task", "claim_review_task"}):
        if target != context["task_id"]:
            raise RuntimeStoreError("permission_denied")
        if operation in _LIFECYCLE:
            bound.arguments["expected_run_id"] = context["run_id"]
    if owned and operation == "heartbeat_claim":
        if target != context["task_id"]:
            raise RuntimeStoreError("permission_denied")
        bound.arguments["claimer"] = context["claim_lock"]
    if owned and operation == "link_tasks":
        if bound.arguments["child_id"] != context["task_id"]:
            raise RuntimeStoreError("permission_denied")
        bound.arguments["expected_child_run_id"] = context["run_id"]
    return handler(*bound.args, **bound.kwargs)
