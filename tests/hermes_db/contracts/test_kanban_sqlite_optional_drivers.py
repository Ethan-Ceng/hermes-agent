"""A real SQLite completion/file flow must not import any optional PG dependency."""

import subprocess
import sys


def test_sqlite_attachment_completion_survives_without_postgresql_imports(tmp_path):
    from tests.gateway.fixtures.local_recovery_probe import child_env
    home = tmp_path / "sqlite-profile"
    home.mkdir()
    code = r'''
import importlib.abc, json, os, sys
from pathlib import Path
class RejectPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'psycopg', 'alembic'}:
            raise AssertionError('SQLite attempted optional PostgreSQL import: ' + fullname)
sys.meta_path.insert(0, RejectPostgres())
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_workspace as workspace
kbc.init_db()
with kbc.connect_closing() as store:
    task = kb.create_task(store, title='SQLite standalone')
    directory = kb.workspaces_root() / task
    directory.mkdir(parents=True)
    workspace.set_workspace_path(store, task, str(directory))
    proof = directory / 'proof.txt'
    proof.write_text('retained', encoding='utf-8')
    assert kb.complete_task(store, task, summary='delivered', metadata={'artifacts': [str(proof)]})
with kbc.connect_closing() as reopened:
    assert kb.get_task(reopened, task).status == 'done'
    attachment, = kb.list_attachments(reopened, task)
    assert Path(attachment.stored_path).read_text(encoding='utf-8') == 'retained'
    assert not directory.exists()
print('SQLITE_STANDALONE_OK')
'''
    env = child_env()
    env.update(HERMES_HOME=str(home), HERMES_KANBAN_HOME=str(home))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert "SQLITE_STANDALONE_OK" in result.stdout
