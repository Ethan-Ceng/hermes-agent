"""Production dispatcher argv, ordinary daemon, adopted worker and model tools on PG."""

from contextlib import contextmanager
import asyncio
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_dispatch as dispatch
from tests.waiting import wait_until

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


class Model(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions":
            # Provider discovery probes Ollama's /api/show on a custom endpoint.
            self.send_error(404)
            return
        self.server.requests.append(body)
        called = {call["function"]["name"] for message in body.get("messages", [])
                  for call in message.get("tool_calls", [])}
        name = "kanban_comment" if "kanban_comment" not in called else "kanban_complete"
        message = {"role": "assistant", "content": "PG_WORKER_DONE"}
        finish = "stop"
        if "kanban_complete" not in called:
            arguments = {"body": "PG_COMMAND_PERSISTED"} if name == "kanban_comment" else {"summary": "PG worker delivered"}
            arguments["task_id"] = self.server.task_id
            message = {"role": "assistant", "content": None, "tool_calls": [{"index": 0, "id": name, "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        payload = {"id": "pg-worker", "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        encoded = json.dumps(payload).encode()
        content_type = "application/json"
        if body.get("stream"):
            payload["choices"][0]["delta"] = payload["choices"][0].pop("message")
            encoded = ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode()
            content_type = "text/event-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def safe_log(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join("[redacted storage detail]" if re.search(r"(?i)dsn|password|postgres(?:ql)?(?:\+psycopg)?://", line)
                     else line for line in lines[-45:])


@contextmanager
def daemon(home, env, *, module="gateway.run"):
    from tests.gateway.test_normal_runtime_boot import control
    from tests.gateway.fixtures.local_recovery_probe import seed_offline_models_dev
    root = Path(__file__).resolve().parents[4]
    seed_offline_models_dev(home)
    with (home / "pg-kanban-owner.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-m", module], cwd=root, env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            def ready():
                if child.poll() is not None:
                    log.flush()
                    raise AssertionError("isolated PG daemon exited\n" + safe_log(home / "pg-kanban-owner.log"))
                try:
                    descriptor = control(home, "identify")
                    return descriptor if descriptor.get("state") == "ready" else None
                except (OSError, ValueError):
                    return None

            descriptor = wait_until(ready, timeout=90, interval=.05, what="isolated PG daemon ready")
            yield descriptor
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def prepare_execution_home(home, config, separate_profile):
    from hermes_cli.config import atomic_config_write
    if not separate_profile:
        return home, "default", "one"
    execution_home = home / "profiles" / "coder"
    execution_home.mkdir(parents=True)
    config = copy.deepcopy(config)
    config["storage"]["postgresql"]["store_id"] = "worker-two"
    atomic_config_write(execution_home / "config.yaml", config)
    shutil.copyfile(home / ".env", execution_home / ".env")
    return execution_home, "coder", "worker-two"


def wait_completion(store, task_id, home):
    try:
        wait_until(lambda: kb.get_task(store, task_id).status == "done", timeout=90, interval=.05,
                   what="PG model tool completion")
    except AssertionError as error:
        paths = (kb.worker_logs_dir() / f"{task_id}.log", home / "pg-kanban-owner.log")
        details = "\n".join(safe_log(path) for path in paths if path.is_file())
        raise AssertionError(f"{error}\n{details}") from error


def run_worker_probe(pg_profiles, tmp_path, monkeypatch, *, owner_module="gateway.run", separate_profile=False):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from hermes_db.integration.kanban_owner import board_reference
    from tests.gateway.fixtures.local_recovery_probe import child_env
    root = Path(__file__).resolve().parents[4]
    guard = tmp_path / "guard"
    guard.mkdir()
    audit = tmp_path / "audit"
    audit.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import json, os, sqlite3, sys\nfrom pathlib import Path\n"
        f"audit = Path({str(audit)!r})\n"
        "(audit / ('guard-' + str(os.getpid()))).write_text(json.dumps({'pid': os.getpid(), 'parent_pid': os.getppid()}))\n"
        "def reject(*args, **kwargs):\n"
        "    (audit / ('attempt-' + str(os.getpid()))).touch()\n"
        "    raise AssertionError('SQLite connection rejected in PG worker business process')\n"
        "sqlite3.connect = reject\n"
        "sys.addaudithook(lambda event, args: reject() if event == 'sqlite3.connect' else None)\n", encoding="utf-8")
    peer = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    peer.requests = []
    thread = threading.Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    launchers = []
    try:
        with pg_profiles("one") as home:
            workspace = home / "workspace"
            workspace.mkdir()
            url = f"http://127.0.0.1:{peer.server_port}/v1"
            config = read_user_config_raw(home / "config.yaml")
            config.update(gateway={"multiplex_profiles": False}, model={"provider": "custom", "default": "pg-loop", "base_url": url},
                auxiliary={"title_generation": {"enabled": False}}, platform_toolsets={"cli": ["terminal", "file"]},
                terminal={"backend": "local"}, agent={"api_max_retries": 1}, kanban={"dispatch_in_gateway": False})
            atomic_config_write(home / "config.yaml", config)
            execution_home, assignee, execution_store_id = prepare_execution_home(home, config, separate_profile)
            monkeypatch.setenv("HERMES_HOME", str(home))
            env = child_env()
            env.update(HOME=str(tmp_path / "user"), USERPROFILE=str(tmp_path / "user"), HERMES_HOME=str(home),
                PYTHONPATH=os.pathsep.join((str(guard), str(root))), PYTHONUNBUFFERED="1", OPENAI_API_KEY="loopback-only",
                OPENAI_BASE_URL=url, HERMES_RUNTIME_DIR=str(execution_home / "runtime"))
            env["HERMES_HOME"] = str(execution_home)
            (tmp_path / "user").mkdir()
            monkeypatch.setattr(dispatch, "_memory_pressure_level", lambda *args: "normal")
            with daemon(execution_home, env, module=owner_module) as first_owner, kbc.connect_closing() as store:
                task_id = kb.create_task(store, title="PG_WORKER_TASK", assignee=assignee, workspace_kind="dir",
                                         workspace_path=str(workspace))
                peer.task_id = task_id
                reference = board_reference(store)

                def spawn(task, path, board=None):
                    from cron import scheduler_worker_env
                    assert store._transactions.engine.pool.checkedout() == 0
                    pin = scheduler_worker_env.pin_hermes_tree_on_pythonpath

                    def instrument(worker_env, repo_root):
                        worker_env = pin(worker_env, repo_root)
                        worker_env["PYTHONPATH"] = os.pathsep.join((str(guard), worker_env.get("PYTHONPATH", "")))
                        return worker_env

                    # Only this wrapper captures test-owned launcher identity; production argv/spawn stays real.
                    with monkeypatch.context() as patch:
                        patch.setenv("PYTHONPATH", env["PYTHONPATH"])
                        patch.setenv("HERMES_HOME", str(home))
                        patch.setattr(scheduler_worker_env, "pin_hermes_tree_on_pythonpath", instrument)
                        pid = dispatch._default_spawn(task, path, board=board, board_owner=reference)
                    launchers.append((pid, task.claim_lock, dispatch._process_fingerprint(pid)))
                    return pid

                result = dispatch.dispatch_once(store, spawn_fn=spawn, max_spawn=1)
                assert [row[0] for row in result.spawned] == [task_id]
                wait_completion(store, task_id, execution_home)
                try:
                    wait_until(lambda: any(event.kind == "worker_result" for event in kb.list_events(store, task_id)),
                               timeout=30, interval=.05, what="PG worker result receipt")
                except AssertionError as error:
                    paths = (kb.worker_logs_dir() / f"{task_id}.log", execution_home / "pg-kanban-owner.log")
                    details = "\n".join(safe_log(path) for path in paths if path.is_file())
                    raise AssertionError(f"{error}\n{details}") from error
                assert [comment.body for comment in kb.list_comments(store, task_id)] == ["PG_COMMAND_PERSISTED"]
                run = kb.latest_run(store, task_id)
                assert run.outcome == "completed" and run.summary == "PG worker delivered"
                bound = next(event for event in kb.list_events(store, task_id) if event.kind == "worker_bound")
                admission = next(event for event in kb.list_events(store, task_id) if event.kind == "owner_admitted")
                assert admission.payload["store_id"] == execution_store_id
                assert Path(admission.payload["profile_home"]) == execution_home
                witnessed = [json.loads(path.read_text()) for path in audit.glob("guard-*")]
                # Windows' venv redirector can be the Popen handle; its Python child runs the business code.
                assert any(item["pid"] == launchers[0][0] or item["parent_pid"] == launchers[0][0] for item in witnessed), witnessed
                assert (audit / f"guard-{first_owner['pid']}").exists()
                assert (audit / f"guard-{bound.payload['pid']}").exists()
                wait_until(lambda: not kb._pid_alive(launchers[0][0]), timeout=30, interval=.05,
                           what="PG submitter result acknowledgement")
                dispatch.reap_worker_zombies()
                exit_status = dispatch._classify_worker_exit(launchers[0][0])
                assert exit_status == ("clean_exit", 0), (
                    exit_status, safe_log(kb.worker_logs_dir() / f"{task_id}.log"), safe_log(execution_home / "pg-kanban-owner.log"),
                    [(event.kind, event.payload) for event in kb.list_events(store, task_id)
                     if event.kind in {"worker_result", "worker_lost"}])
                assert list(audit.glob("attempt-*")) == []
                params = dict(board=store.slug, task_id=task_id, run_id=run.id, claim_lock=launchers[0][1], owner=reference)
            with kbc.connect_closing() as reopened:
                assert kb.get_task(reopened, task_id).status == "done"
                assert kb.latest_run(reopened, task_id).id == run.id
            requests = len(peer.requests)
            with daemon(execution_home, env, module=owner_module) as replacement:
                assert replacement["authority_epoch"] > first_owner["authority_epoch"]

                async def read_saved_attempt():
                    from tests.gateway.fixtures.local_recovery_probe import rpc, websocket
                    async with websocket(execution_home, replacement) as connection:
                        first = await rpc(connection, "kanban.run", **params)
                        second = await rpc(connection, "kanban.run", **params)
                        assert "result" in first and "result" in second
                        assert first["result"]["session_id"] == second["result"]["session_id"]
                        assert first["result"]["receipt"]["status"] == "terminal", first["result"]["receipt"]["status"]
                        assert second["result"]["receipt"]["status"] == "terminal", second["result"]["receipt"]["status"]
                        result = await rpc(connection, "kanban.result", **params)
                        assert result.get("result", {}).get("exit_code") == 0

                asyncio.run(read_saved_attempt())
                assert len(peer.requests) == requests, [
                    {"model": request.get("model"), "has_tools": bool(request.get("tools")),
                     "task_in_messages": task_id in json.dumps(request.get("messages", []))}
                    for request in peer.requests[requests:]]
                with kbc.connect_closing() as restored:
                    assert sum(event.kind == "worker_bound" for event in kb.list_events(restored, task_id)) == 1
                    assert [comment.body for comment in kb.list_comments(restored, task_id)] == ["PG_COMMAND_PERSISTED"]
                assert list(audit.glob("attempt-*")) == []
            if separate_profile:
                from hermes_cli.db_setup import _owning_profile
                with _owning_profile(execution_home), kbc.connect_closing() as execution_board:
                    assert kb.list_tasks(execution_board) == []
    finally:
        for pid, lock, birth in launchers:
            dispatch._terminate_reclaimed_worker(pid, lock, started_at=birth)
        peer.shutdown()
        peer.server_close()
        thread.join(timeout=5)


def test_real_pg_kanban_worker_never_opens_sqlite_and_persists_tools(pg_profiles, tmp_path, monkeypatch):
    run_worker_probe(pg_profiles, tmp_path, monkeypatch)
