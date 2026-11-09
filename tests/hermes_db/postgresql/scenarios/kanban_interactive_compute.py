"""A real adopted compute calls ordinary Kanban tools and reserves a read-only child."""

import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import psutil


def main():
    from agent.runtime_session_store import RuntimeSessionStore, WorkerRPC, call_off_event_loop
    from agent.runtime_session_child import reserve_child_store
    from agent.runtime_worker_context import worker_store_context
    from agent.delegation_context import delegated_child_context
    from hermes_cli.process_identity import worker_birth
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    from hermes_db.domains.kanban.routing.wire import pack
    from model_tools import handle_function_call
    import tools.kanban_tools  # register the actual application handlers
    command = json.loads(sys.stdin.readline())
    home = Path(command["home"])
    rpc = WorkerRPC(home)
    scope = dict(profile_id=str(home), session_id=command["session_id"], execution_id="interactive-compute", generation=0,
                 pid=os.getpid(), birth=worker_birth(psutil.Process()), secret="private-interactive-compute")
    rpc("worker.register", **scope, kind="compute")
    scope["epoch"] = rpc("worker.adopt", **scope)["owner_epoch"]
    store = RuntimeSessionStore(rpc, scope, home / "worker-outboxes" / "interactive-compute")
    try:
        result = json.loads(handle_function_call("kanban_create", {"title": "ordinary Worker", "workspace_kind": "scratch", "assignee": "default"}))
        assert result.get("ok"), result
        task = result["task_id"]
        result = json.loads(handle_function_call("kanban_comment", {"task_id": task, "body": "ordinary tool persisted"}))
        assert result.get("ok"), result
        with kbc.connect_closing() as proxy:
            attachment = kb.store_attachment_bytes(proxy, task, "maximum.bin", b"\x00" * kb.KANBAN_ATTACHMENT_MAX_BYTES)
            assert kb.get_attachment(proxy, attachment).size == kb.KANBAN_ATTACHMENT_MAX_BYTES
            owner = proxy.context["owner"]
        child = reserve_child_store(store)
        try:
            with delegated_child_context(child.reserved_session_id), worker_store_context(child):
                result = json.loads(handle_function_call("kanban_show", {"task_id": task}))
                assert result.get("task", {}).get("id") == task, result
                result = json.loads(handle_function_call("kanban_comment", {"task_id": task, "body": "forbidden"}))
                assert "error" in result, result
                with kbc.connect_closing() as proxy:
                    assert proxy.worker_store is child
                    assert kb.get_task(proxy, task).title == "ordinary Worker"
                    try:
                        kb.add_comment(proxy, task, "child", "forbidden direct")
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("child mutation escaped the local store guard")
                payload = {"target": {"board": owner["board"], "board_id": owner["board_id"]},
                    "args": pack([task, "child", "forbidden RPC"]), "kwargs": pack({})}
                try:
                    call_off_event_loop(child.rpc, "worker.kanban.command", **child.scope,
                                        operation="add_comment", payload=payload, command_id=uuid4().hex)
                except Exception as error:
                    assert "permission_denied" in str(error), type(error).__name__
                else:
                    raise AssertionError("owner accepted a delegated child mutation")
        finally:
            child.close()
        store.finish()
        Path(command["receipt"]).write_text(json.dumps({"task_id": task, "attachment_id": attachment,
            "child_session": child.reserved_session_id, "pid": os.getpid()}), encoding="utf-8")
    finally:
        store.close()


if __name__ == "__main__":
    main()
