"""Off-turn surface consumers follow the owning backend, not local SQLite file heuristics."""

from pathlib import Path
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_idle_exit_keeps_gateway_for_pg_kanban_work_in_any_served_profile(pg_profiles):
    from gateway.run_idle_exit import _kanban_busy, _kanban_busy_for_homes
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    with pg_profiles("one") as first, kbc.connect_closing() as board:
        task = kb.create_task(board, title="keep the owner alive")
        assert _kanban_busy() is not None
    with pg_profiles("two") as second:
        assert _kanban_busy() is None
        assert _kanban_busy_for_homes([second, first]) is not None
    with pg_profiles("one"), kbc.connect_closing() as board:
        assert kb.complete_task(board, task, result="completed")
        assert _kanban_busy() is None


def test_pg_update_guard_never_inspects_legacy_sqlite_or_offers_native_snapshot_recovery(pg_profiles, monkeypatch):
    from hermes_cli import update_downgrade_guard as guard
    with pg_profiles("one") as home:
        (home / "state.db").write_bytes(b"inactive legacy data must remain unopened")
        root = Path(__file__).resolve().parents[3]
        assert guard.would_refuse(root, "older", home, git=lambda *args: 1)
        assert not guard.would_refuse(root, "forward", home, git=lambda *args: 0)
        monkeypatch.setattr(guard, "_updater_git", lambda *args: lambda *_args: 1)
        reason = guard.downgrade_refusal(None, root, "older", home)
        assert "PostgreSQL" in reason and "/snapshot restore" not in reason
        assert (home / "state.db").read_bytes() == b"inactive legacy data must remain unopened"


def test_post_update_completion_probes_pg_schema_and_never_sqlite_runtime(pg_profiles, monkeypatch, capsys):
    from hermes_cli.update_cmd_maint import _print_verified_update_completion
    from hermes_db.infra.backends.sqlite import runtime as sqlite_runtime
    def forbidden(*args, **kwargs):
        pytest.fail("PG update verification must not create even an in-memory SQLite probe")
    monkeypatch.setattr(sqlite_runtime, "probe_sqlite_runtime", forbidden)
    with pg_profiles("one"):
        assert _print_verified_update_completion("✓ Update complete!")
        assert "Update complete" in capsys.readouterr().out
        monkeypatch.setattr("hermes_db.health.configured_probe", lambda _home: {"backend": "postgresql", "status": "degraded"})
        assert not _print_verified_update_completion("✓ Update complete!")
        assert "not ready" in capsys.readouterr().out
