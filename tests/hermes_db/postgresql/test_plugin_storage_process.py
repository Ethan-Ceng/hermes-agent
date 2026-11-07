"""Database-owned CAS and quotas must hold across independent interpreters."""

from pathlib import Path
import subprocess
import sys
import pytest
from plugins.plugin_storage import plugin_store, PluginStorageQuotaError
from plugins.plugin_storage_types import MAX_VALUE_BYTES

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def child_args(home, role):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    env = child_env()
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
    return [sys.executable, str(Path(__file__).with_name("scenarios") / "portable_plugins.py"), role], env


def race(home, roles):
    children = []
    try:
        for role in roles:
            args, env = child_args(home, role)
            children.append(subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8"))
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        results = [child.communicate(timeout=60) for child in children]
        assert all(child.returncode == 0 for child in children), [stderr for _, stderr in results]
        return sorted(stdout.strip() for stdout, _ in results)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def test_two_processes_cas_exactly_one_winner_and_new_process_reads(pg_profiles):
    with pg_profiles("one") as home:
        assert race(home, ("cas-a", "cas-b")) == ["CAS_COMMITTED", "CAS_REFUSED"]
        args, env = child_args(home, "read")
        result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert "PG_PLUGIN_RESTART_READ_OK" in result.stdout
        assert plugin_store("discord", namespace="race").get("same").value in {"cas-a", "cas-b"}


def test_actual_namespace_byte_quota_competes_across_processes(pg_profiles):
    with pg_profiles("one") as home:
        store = plugin_store("discord", namespace="quota")
        value = "x" * (MAX_VALUE_BYTES - 2)
        for index in range(15):
            store.put(f"block-{index:02d}", value)
        assert race(home, ("quota-a", "quota-b")) == ["QUOTA_COMMITTED", "QUOTA_REFUSED"]
        with pytest.raises(PluginStorageQuotaError):
            store.put("over-quota", 0)
        assert len(store.scan()) == 16
        assert store.get("over-quota") is None
        assert plugin_store("discord", namespace="separate").put("over-quota", 0).value == 0
        with pytest.raises(PluginStorageQuotaError):
            store.put("too-large", "x" * MAX_VALUE_BYTES)
    with pg_profiles("two"):
        assert plugin_store("discord", namespace="quota").put("over-quota", 0).value == 0
