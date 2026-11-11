"""Fresh installed payload probes for configuration-selected independent datasets."""

import json
import os
from pathlib import Path
import subprocess

import pytest


_PROBE = r'''
import importlib.util,json,os,sys
from pathlib import Path
source,home=map(Path,sys.argv[1:3])
expected,action,marker=sys.argv[3:]
attempts=[]
def audit(event,args):
    if event=='sqlite3.connect':
        attempts.append(True)
        if expected!='sqlite':
            raise AssertionError('SQLite connection attempted in PG selection process')
sys.addaudithook(audit)
optional={name:importlib.util.find_spec(name) is not None for name in ('sqlalchemy','psycopg','alembic','mautrix','asyncpg')}
if expected=='sqlite':
    assert not any(optional.values()),'SQLite payload must actually lack PG and SDK dependencies'
import hermes_db
assert Path(hermes_db.__file__).resolve().is_relative_to(source/'hermes_db')
from hermes_db.errors import StorageError
report={'pid':os.getpid(),'sqlite_attempts':0,'optional_dependencies':optional}
try:
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_cli.db_sessions import open_session_store
    settings,scope=resolve_db_configuration(home)
    report['backend']=settings.backend
    assert settings.backend==expected
    if expected=='sqlite' and action=='write':
        from hermes_cli.db_session_schema import initialize_new_profile_sessions
        initialize_new_profile_sessions(home)
    with open_session_store(db_path=home/'state.db') as store:
        ids=('sqlite-marker','pg-marker')
        report['before_visible']=[sid for sid in ids if store.get_session(sid) is not None]
        if action=='write':
            assert store.get_session(marker) is None
            store.create_session(marker,'cli')
            store.append_message(marker,'user',expected+' durable history')
        report['visible']=[sid for sid in ids if store.get_session(sid) is not None]
        report['history']={sid:store.get_messages(sid)[0]['content'] for sid in report['visible']}
except StorageError as exc:
    report['error_type']=type(exc).__name__
except BaseException as exc:
    print(json.dumps({'unexpected_error_type':type(exc).__name__}))
    raise SystemExit(1) from None
finally:
    if expected=='postgresql' and optional['sqlalchemy']:
        from hermes_db.infra.backends.postgresql.engine import close_engines
        close_engines()
report['sqlite_attempts']=len(attempts)
print(json.dumps(report))
'''


def payload_process(request, home, backend, action, marker="", *, python_backend=None):
    source = request.config.getoption("--hermes-distribution-source")
    executable = request.config.getoption(f"--hermes-{python_backend or backend}-python")
    if not source or not executable:
        pytest.skip("Explicit current PM-built independent source and payload interpreters required")
    assert Path(executable).is_file()
    source = Path(source).resolve()
    assert source != Path(__file__).resolve().parents[2] and not (source / ".git").exists()
    env = dict(os.environ)
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               HERMES_RUNTIME_DIR=str(home / "runtime"), PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    result = subprocess.run([executable, "-I", "-c", _PROBE, str(source), str(home), backend, action, marker],
                            cwd=home, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    # Never attach child stderr: unexpected storage failures can contain secret material.
    assert result.returncode == 0, f"dataset child exited {result.returncode}; diagnostic withheld"
    report = json.loads(result.stdout.splitlines()[-1])
    assert "unexpected_error_type" not in report
    return report
