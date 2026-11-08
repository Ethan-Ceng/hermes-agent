"""Launch witnesses from fresh interpreters; configuration and credentials stay in private files."""

import json
from pathlib import Path
import re
import subprocess
import sys


def run(backend, role, homes, *, matrix=False):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    root = Path(__file__).resolve().parents[2]
    env = child_env()
    env.update(HERMES_HOME=str(homes[0]), HOME=str(homes[0]), USERPROFILE=str(homes[0]), PYTHONPATH=str(root),
               HERMES_RUNTIME_DIR=str(homes[0] / "runtime"), HERMES_VERIFY_ON_STOP="1")
    command = [sys.executable, "-m", "tests.hermes_db.single_backend_process", backend, role, *map(str, homes)]
    if matrix:
        command.append("--matrix")
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)
    # Storage errors are sanitized by production boundaries; never attach private configuration.
    diagnostic = "\n".join("[redacted storage detail]" if re.search(r"(?i)dsn|password|postgres(?:ql)?(?:\+psycopg)?://", line) else line
                           for line in result.stderr.splitlines())
    assert result.returncode == 0, diagnostic
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["backend"] == backend and report["role"] == role
    assert len(report["domains"]) == (10 if backend == "postgresql" or matrix else 9)
    assert report["profiles"] == len(homes)
    assert not (homes[0].parent / f"sqlite-attempt-{report['pid']}").exists()
    return report


def prepare_workspace(home):
    workspace = home / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
