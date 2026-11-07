"""Ordinary adopted Worker, real tools/child/upload RPC, owner restart, SQLite rejected."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
from tests.hermes_db.postgresql.scenarios.kanban_full_gateway import daemon, safe_log

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_real_interactive_worker_and_child_survive_owner_restart(pg_profiles, tmp_path):
    from hermes_cli.config import atomic_config_write, read_user_config_raw
    from tests.gateway.fixtures.local_recovery_probe import child_env, rpc, websocket
    guard, audit = tmp_path / "guard", tmp_path / "audit"
    guard.mkdir()
    audit.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import os, sqlite3, sys\nfrom pathlib import Path\n"
        f"audit = Path({str(audit)!r})\n"
        "(audit / ('guard-' + str(os.getpid()))).touch()\n"
        "def reject(*args, **kwargs):\n"
        "    (audit / ('attempt-' + str(os.getpid()))).touch()\n"
        "    raise AssertionError('SQLite rejected in PG business process')\n"
        "sqlite3.connect = reject\n"
        "sys.addaudithook(lambda event, args: reject() if event == 'sqlite3.connect' else None)\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[3]
    with pg_profiles("one") as home:
        config = read_user_config_raw(home / "config.yaml")
        config.update(gateway={"multiplex_profiles": False}, model={"provider": "custom", "default": "pg-test",
            "base_url": "http://127.0.0.1:9/v1", "context_length": 65536}, auxiliary={"title_generation": {"enabled": False}})
        atomic_config_write(home / "config.yaml", config)
        env = child_env()
        user = tmp_path / "user"
        user.mkdir()
        env.update(HOME=str(user), USERPROFILE=str(user), HERMES_HOME=str(home), HERMES_RUNTIME_DIR=str(home / "runtime"), OPENAI_API_KEY="loopback-only",
            PYTHONPATH=os.pathsep.join((str(guard), str(root))), PYTHONUNBUFFERED="1")
        module = "tests.hermes_db.postgresql.scenarios.kanban_session_owner"
        receipt, log_path = home / "worker-receipt.json", home / "interactive-worker.log"
        with daemon(home, env, module=module) as first:
            async def create():
                async with websocket(home, first) as ws:
                    result = await rpc(ws, "session.create", request_id="interactive", source="cli", toolsets=["kanban"])
                    assert "result" in result, result
                    return result["result"]["session_id"]
            try:
                session_id = asyncio.run(create())
            except Exception as error:
                raise AssertionError(safe_log(home / "pg-kanban-owner.log")) from error
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run([sys.executable, "-m", "tests.hermes_db.postgresql.scenarios.kanban_interactive_compute"],
                    input=json.dumps({"home": str(home), "session_id": session_id, "receipt": str(receipt)}),
                    cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=180, check=False)
            assert result.returncode == 0, safe_log(log_path)
            saved = json.loads(receipt.read_text())
            assert (audit / f"guard-{first['pid']}").exists()
            assert (audit / f"guard-{saved['pid']}").exists()
            assert not list(audit.glob("attempt-*"))
        with daemon(home, env, module=module) as second, kbc.connect_closing() as store:
            assert second["authority_epoch"] > first["authority_epoch"]
            assert kb.get_task(store, saved["task_id"]).title == "ordinary Worker"
            assert [comment.body for comment in kb.list_comments(store, saved["task_id"])] == ["ordinary tool persisted"]
            attachment, = kb.list_attachments(store, saved["task_id"])
            assert attachment.id == saved["attachment_id"]
            assert Path(attachment.stored_path).read_bytes() == b"\x00" * kb.KANBAN_ATTACHMENT_MAX_BYTES
            assert not list(audit.glob("attempt-*"))
    with pg_profiles("two"), kbc.connect_closing() as other:
        assert kb.get_task(other, saved["task_id"]) is None
