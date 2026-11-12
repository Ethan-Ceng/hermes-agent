"""Probe installed source bundles with -I from outside their tree, using only exported test data."""

import json
from pathlib import Path
import subprocess

import pytest


BUSINESS_PROBE = r'''
import json, os, sys
from pathlib import Path
import hermes_db
source, forbidden, root = map(Path, sys.argv[1:4])
backend, role, sdk, private, schema, database = sys.argv[4:]
assert Path(hermes_db.__file__).resolve().is_relative_to(source / 'hermes_db')
assert forbidden not in {Path(path).resolve() for path in sys.path}
# The installed application was imported first; test drivers come from the immutable bundle.
sys.path.insert(0, str(source))
from tests.hermes_db.single_backend_guard import install
attempts = install(backend, root / 'admin-storage-attempt', matrix=sdk == 'matrix')
homes = [root / 'one', root / 'two'] if backend == 'postgresql' else [root / 'one']
if role == 'write':
    from hermes_cli.config import atomic_config_write
    if backend == 'postgresql':
        from dataclasses import replace
        from tests.hermes_db.pg_support import read_test_config
        from hermes_db.infra.postgresql.engine import get_engine
        from hermes_db.schema import upgrade_schema
        from sqlalchemy import text
        configured = read_test_config(private)
        settings = replace(configured.settings, schema=schema)
        with get_engine(settings).connect() as conn:
            assert conn.scalar(text('SELECT current_database()')) == database == configured.database
            marker = conn.scalar(text("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname=:schema"), {'schema': schema})
            assert marker == 'hermes-pg-tests:' + schema.removeprefix('hermes_test_')
        assert upgrade_schema(settings)['ready'] and upgrade_schema(settings)['ready']
    for home in homes:
        home.mkdir()
        config = {'storage': {'backend': backend}}
        if backend == 'postgresql':
            config['storage']['postgresql'] = dict(schema=schema, store_id=home.name, pool_size=2, max_overflow=0, connection_budget=2)
            secret = home / '.env'
            secret.write_text('HERMES_POSTGRES_DSN=' + json.dumps(settings.dsn) + '\n', encoding='utf-8')
            secret.chmod(0o600)
        atomic_config_write(home / 'config.yaml', config)
        from tests.hermes_db.single_backend_support import prepare_workspace
        prepare_workspace(home)
else:
    homes.reverse()
os.environ['HERMES_HOME'] = str(homes[0])
os.environ['HERMES_VERIFY_ON_STOP'] = '1'
from tests.hermes_db.single_backend_process import main
sys.argv = ['business', backend, role, *map(str, homes), *(['--matrix'] if sdk == 'matrix' else [])]
main()
assert not (root / 'admin-storage-attempt').exists()
if backend == 'postgresql':
    assert not attempts and not tuple(root.glob('sqlite-attempt-*'))
'''


def business_process(request, root, backend, role, *, matrix=False, schema="", database=""):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    payload = "sqlite-matrix" if backend == "sqlite" and matrix else backend
    executable = request.config.getoption(f"--hermes-{payload}-python")
    source = request.config.getoption("--hermes-distribution-source")
    if not executable or not source:
        pytest.skip("Explicit PM-built independent bundle and interpreters are required")
    source = Path(source).resolve()
    checkout = Path(__file__).resolve().parents[2]
    assert source != checkout and not (source / ".git").exists()
    env = child_env()
    env.update(HERMES_HOME=str(root), HOME=str(root), USERPROFILE=str(root), HERMES_RUNTIME_DIR=str(root / "runtime"))
    private = request.config.getoption("--postgres-test-config") or ""
    command = [executable, "-I", "-c", BUSINESS_PROBE, str(source), str(checkout), str(root), backend, role,
               "matrix" if matrix else "core", private, schema, database]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)
    from tests.hermes_db.single_backend_support import safe_diagnostic
    assert result.returncode == 0, safe_diagnostic(result.stderr)
    return json.loads(result.stdout.splitlines()[-1])
