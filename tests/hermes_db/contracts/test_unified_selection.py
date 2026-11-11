"""One Profile selection shared by session and subsequent domain resources."""

from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import pytest

from hermes_cli.config import atomic_config_write
from hermes_cli.db_setup import resolve_db_configuration
from hermes_db.errors import StorageConfigurationError


@pytest.mark.parametrize("legacy", [{}, {"backend": "sqlite"}, {"backend": "postgresql"}])
def test_legacy_session_selection_is_rejected_even_with_new_selection(tmp_path, legacy):
    from hermes_cli.db_setup import storage_backend
    atomic_config_write(tmp_path / "config.yaml", {"storage": {"backend": "sqlite", "session": legacy}})
    for read in (storage_backend, resolve_db_configuration):
        with pytest.raises(StorageConfigurationError, match=r"storage\.session.*storage\.backend"):
            read(tmp_path)
    assert not (tmp_path / "state.db").exists()


def test_threaded_profile_selection_uses_effective_config_and_own_secrets(tmp_path):
    from hermes_cli.db_setup import storage_backend
    from hermes_constants import get_hermes_home

    homes = [tmp_path / "first", tmp_path / "second"]
    for index, home in enumerate(homes):
        home.mkdir()
        atomic_config_write(home / "config.yaml", {"storage": {
            "backend": "postgresql", "postgresql": {"schema": "hermes", "store_id": f"store-{index}"}}})
        (home / ".env").write_text(f"HERMES_POSTGRES_DSN=postgresql://u:secret-{index}@localhost/test\n")
    caller_home = get_hermes_home()

    def resolve(index):
        home = homes[index]
        settings, scope = resolve_db_configuration(home)
        assert storage_backend(home) == settings.backend == "postgresql"
        assert scope.profile_home == home.resolve()
        assert scope.store_id == f"store-{index}"
        assert f"secret-{index}" in settings.postgresql.dsn
        assert get_hermes_home() == caller_home

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(resolve, [0, 1] * 4))
    assert get_hermes_home() == caller_home


def test_sqlite_selection_and_business_work_without_postgres_imports(tmp_path):
    code = r'''
import importlib.abc
import sys
class NoPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'psycopg', 'sqlalchemy', 'alembic'}:
            raise ImportError('PG dependencies deliberately unavailable')
sys.meta_path.insert(0, NoPostgres())
from pathlib import Path
from hermes_cli.db_session_schema import initialize_new_profile_sessions
from hermes_cli.db_setup import open_profile_db, storage_backend
assert storage_backend(sys.argv[1]) == 'sqlite'
initialize_new_profile_sessions(Path(sys.argv[1]))
with open_profile_db(sys.argv[1]) as db:
    db.sessions.create_session('independent', source='cli')
    db.sessions.append_message('independent', role='user', content='persisted')
with open_profile_db(sys.argv[1]) as db:
    assert db.sessions.get_messages_as_conversation('independent')[0]['content'] == 'persisted'
from hermes_cli import projects_db as pdb
with pdb.connect_closing(profile_home=sys.argv[1]) as store:
    pid = pdb.create_project(store, name='Independent Projects')
with pdb.connect_closing(profile_home=sys.argv[1]) as store:
    assert pdb.get_project(store, pid).name == 'Independent Projects'
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from cron import executions as ex, incidents as inc
attempt = ex.create_execution('independent', source='test')
assert ex.finish_execution(attempt['id'], success=True)['status'] == 'completed'
incident, new = inc.upsert_incident('independent', 'failure')
assert new and inc.get_incident(incident)['state'] == 'detected'
from cron import delivery_queue as queue
queue.enqueue('queue-independent', {'id': 'queue-job'}, 'queued')
assert queue.drain(lambda *args: None) == 1
assert queue.get_status('queue-independent')['status'] == 'delivered'
from cron import notepad
notepad.set_note('independent', 'cursor', 'persisted')
assert notepad.get_note('independent', 'cursor') == 'persisted'
from pathlib import Path
Path.home = lambda: Path(sys.argv[1])
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
kb.create_board('independent')
with kbc.connect_closing(board='independent') as store:
    parent = kb.create_task(store, title='parent', workspace_kind='scratch')
    child = kb.create_task(store, title='child', workspace_kind='scratch', parents=[parent])
    assert kb.get_task(store, child).status == 'todo'
    assert kb.unlink_tasks(store, parent, child)
with kbc.connect_closing(board='independent') as store:
    assert kb.get_task(store, child).status == 'ready'
'''
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
