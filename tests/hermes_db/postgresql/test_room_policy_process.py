"""A real successor process reuses and advances its persisted PG projection."""

from pathlib import Path
import subprocess
import sys

import pytest

from gateway import hosted_rooms as rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
from tests.hermes_db.postgresql.test_room_policy import create, append

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_policy_cursor_and_opaque_watermark_survive_new_python_process(pg_profiles):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    with pg_profiles("one") as home:
        location = rooms.default_db_path()
        create(location)
        append(location, "source", "message.user", dict(text="hello", thread_id="讨论\x00🙂"))
        append(location, "failure", "turn.failed", dict(thread_id="讨论\x00🙂", discussion_event_id="source", member_id="ops", seen_through_seq=1, task_id="task"))
        before = HostedRoomPolicyCheckpoint(location).snapshot(room_id="room", latest_seq=2)
        code = r'''
import sqlite3, sys
def reject(*args, **kwargs):
    raise AssertionError("SQLite connection rejected in PG policy restart")
sqlite3.connect = reject
sys.addaudithook(lambda event, args: reject() if event == 'sqlite3.connect' else None)
from gateway import hosted_rooms as rooms
from gateway.hosted_room_policy_checkpoint import HostedRoomPolicyCheckpoint
location = rooms.default_db_path()
checkpoint = HostedRoomPolicyCheckpoint(location)
restored = checkpoint.snapshot(room_id="room", latest_seq=2)
assert restored.through_seq == 2 and restored.watermarks == {("讨论\x00🙂", "ops"): 1}
assert checkpoint.publication_exists(room_id="room", task_id="task", status="failed", execution_generation=1)
rooms.append_event(location, room_id="room", event_id="after-restart", kind="message.user", actor={"kind":"user","id":"alice"},
    payload={"text":"new","thread_id":"讨论\x00🙂"}, authority_gateway_id="owner", authority_epoch=1)
assert checkpoint.snapshot(room_id="room", latest_seq=3).through_seq == 3
print("PG_ROOM_POLICY_RESTART_OK")
'''
        env = child_env()
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[3], env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert "PG_ROOM_POLICY_RESTART_OK" in result.stdout
        after = HostedRoomPolicyCheckpoint(location).snapshot(room_id="room", latest_seq=3)
        assert after.through_seq == 3 and after.watermarks == before.watermarks
        assert after.events[-1]["event_id"] == "after-restart"
