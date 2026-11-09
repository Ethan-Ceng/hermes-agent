"""Per-job durable notes, exact byte quotas and actual Cron consumers."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_notepad_persistence_scope_render_and_job_removal(pg_profiles):
    from cron import jobs, notepad
    with pg_profiles("one") as home:
        job = jobs.create_job(prompt="check", schedule="every 1h")
        notepad.set_note(job["id"], "cursor\x00🙂", "中文\x00🙂")
        assert notepad.get_note(job["id"], "cursor\x00🙂") == "中文\x00🙂"
        assert "中文\x00🙂" in notepad.render_notepad_section(job["id"])
        assert notepad.render_notepad_section("empty") == ""
        assert not (home / "cron/notepad.db").exists()
    with pg_profiles("two"):
        notepad.set_note(job["id"], "cursor\x00🙂", "other")
    from hermes_db.backends.postgresql.engine import close_engines
    close_engines()
    with pg_profiles("one"):
        assert notepad.get_note(job["id"], "cursor\x00🙂") == "中文\x00🙂"
        import subprocess
        import sys
        code = r'''
import sys, sqlite3
def reject(*args, **kwargs):
    raise AssertionError('SQLite in PG notepad child')
sqlite3.connect = reject
from hermes_constants import set_hermes_home_override
set_hermes_home_override(sys.argv[1])
from cron import notepad
assert notepad.get_note(sys.argv[2], 'cursor\x00🙂') == '中文\x00🙂'
notepad.set_note(sys.argv[2], 'child', 'restarted')
'''
        result = subprocess.run([sys.executable, "-c", code, str(home), job["id"]], capture_output=True,
                                text=True, check=False, timeout=30)
        assert result.returncode == 0, result.stderr
        assert notepad.get_note(job["id"], "child") == "restarted"
        assert jobs.remove_job(job["id"])
        assert notepad.list_notes(job["id"]) == []
    with pg_profiles("two"):
        assert notepad.get_note(job["id"], "cursor\x00🙂") == "other"


def test_utf8_limits_and_concurrent_job_quota(pg_profiles, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from cron import notepad

    with pg_profiles("one"):
        monkeypatch.setattr(notepad, "MAX_JOB_TOTAL_BYTES", 100)
        with pytest.raises(ValueError, match="value too large"):
            notepad.set_note("job", "huge", "🙂" * (notepad.MAX_VALUE_BYTES // 4 + 1))
        def write(key):
            try:
                notepad.set_note("job", key, "🙂" * 15)
                return True
            except ValueError as error:
                assert "notepad full" in str(error)
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = [future.result() for future in [workers.submit(copy_context().run, write, key) for key in ("a", "b")]]
        assert sorted(results) == [False, True]
        notes = notepad.list_notes("job")
        assert len(notes) == 1
        key = notes[0]["key"]
        with pytest.raises(ValueError, match="notepad full"):
            notepad.set_note("job", key, "🙂" * 25)
        assert notepad.get_note("job", key) == "🙂" * 15
        assert notepad.delete_note("job", key)
        assert notepad.clear_notepad("job") == 0


def test_storage_failure_cannot_render_as_empty_and_cleanup_is_reported(pg_profiles, caplog):
    from sqlalchemy import text
    from cron import jobs, notepad
    from hermes_cli.db_setup import resolve_db_configuration
    from hermes_db.backends.postgresql.engine import get_engine
    from hermes_db.errors import StorageError

    with pg_profiles("one"):
        job = jobs.create_job(prompt="check", schedule="every 1h")
        notepad.set_note(job["id"], "cursor", "old")
        settings, _scope = resolve_db_configuration()
        with get_engine(settings.postgresql).begin() as conn:
            quoted = conn.dialect.identifier_preparer.quote(settings.postgresql.schema)
            conn.execute(text(f"DROP TABLE {quoted}.cron_notepad"))
        with pytest.raises(StorageError):
            notepad.render_notepad_section(job["id"])
        assert jobs.remove_job(job["id"])
        assert "Notepad cleanup failed" in caplog.text
