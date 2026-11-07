"""Actual legacy Matrix SDK storage remains usable with every Hermes PG dependency absent."""

from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.platforms("linux")
def test_sqlite_sdk_storage_independent_of_pg_stack(tmp_path):
    pytest.importorskip("mautrix.crypto")
    from tests.gateway.fixtures.local_recovery_probe import child_env
    home = tmp_path / "matrix-sqlite"
    home.mkdir()
    (home / "config.yaml").write_text("storage:\n  backend: sqlite\n", encoding="utf-8")
    env = child_env()
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home), PYTHONPATH=str(Path(__file__).resolve().parents[4]))
    script = Path(__file__).with_name("sqlite_crypto_scenario.py")
    result = subprocess.run([sys.executable, str(script)], env=env, text=True, encoding="utf-8", capture_output=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "MATRIX_SQLITE_WITHOUT_PG_OK" in result.stdout
