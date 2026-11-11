"""Real competing processes and restart recovery, not connection mocks or file absence."""

from pathlib import Path
import subprocess
import sys
from datetime import timedelta
import pytest
from hermes_db.domains.metrics import policy as native
from hermes_cli.observability import shared_metrics_postgres as metric_export
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_contract import CLIENT_ACTIVE_METRIC
from tests.hermes_db.postgresql.test_metrics_store import DAY, RESOURCE

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def command(home, role):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    env = child_env()
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home))
    args = [sys.executable, str(Path(__file__).with_name("scenarios") / "metrics.py"), role]
    return args, env


def test_actual_processes_aggregate_latch_and_restart_package(pg_profiles):
    with pg_profiles("one") as home:
        args, env = command(home, "increment")
        children = [subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8") for _ in range(2)]
        try:
            for child in children:
                child.stdin.write("go\n")
                child.stdin.flush()
            results = [child.communicate(timeout=60) for child in children]
            assert all(child.returncode == 0 for child in children), [stderr for _, stderr in results]
            assert all("PG_METRICS_INCREMENT_OK" in stdout for stdout, _ in results)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
        assert SharedMetricsStore().counter_snapshot()[0]["value"] == 41
        args, env = command(home, "read_package")
        result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert "PG_METRICS_RESTART_PACKAGE_OK" in result.stdout


def test_export_after_file_failure_recovers_in_new_actual_process(pg_profiles, monkeypatch):
    with pg_profiles("one") as home:
        monkeypatch.setattr(native, "_utc_now", lambda: DAY + timedelta(hours=12))
        store = SharedMetricsStore()
        store.record_counter(CLIENT_ACTIVE_METRIC, {}, RESOURCE)
        def refuse(*args, **kwargs):
            raise OSError("injected file refusal")
        monkeypatch.setattr(metric_export, "atomic_json_write", refuse)
        with pytest.raises(OSError, match="file refusal"):
            store.create_and_export_package()
        args, env = command(home, "export_recovery")
        result = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        assert "PG_METRICS_EXPORT_RECOVERY_OK" in result.stdout
