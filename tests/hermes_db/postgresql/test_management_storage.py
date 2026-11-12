"""Destructive maintenance is explicitly Profile/store scoped and preserves files on uncertainty."""

from pathlib import Path
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def seed(home):
    from hermes_cli.db_setup import open_profile_db
    from plugins.plugin_storage import plugin_store
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    with open_profile_db(home) as handle:
        handle.sessions.create_session("same", "cli")
        handle.sessions.append_message("same", "user", "persistent")
    plugin_store("discord", namespace="test-wipe").put("same", {"persistent": True})
    with kbc.connect_closing() as board:
        return kb.create_task(board, title="persist before removal")


def test_data_only_removal_purges_owned_pg_domains_then_files_and_preserves_other_store(pg_profiles):
    from hermes_cli.data_cleanup import plan_data_removal, remove_data
    from hermes_cli.db_setup import open_profile_db
    from plugins.plugin_storage import plugin_store
    from hermes_cli import kanban_db as kb, kanban_db_connect as kbc
    with pg_profiles("two") as other_home:
        other_task = seed(other_home)
    with pg_profiles("one") as home:
        task = seed(home)
        config, secret = (home / "config.yaml").read_bytes(), (home / ".env").read_bytes()
        plan = plan_data_removal(home, Path(__file__).resolve().parents[3])
        assert plan.database is not None and plan.database.store_id == "one"
        removed, failed = remove_data(plan)
        assert failed == [] and home / "config.yaml" in removed
        (home / "config.yaml").write_bytes(config)
        (home / ".env").write_bytes(secret)
        with open_profile_db(home) as handle:
            assert handle.sessions.get_session("same") is None
        assert plugin_store("discord", namespace="test-wipe").get("same") is None
        with kbc.connect_closing() as board:
            assert kb.get_task(board, task) is None
    with pg_profiles("two"), open_profile_db(other_home) as handle, kbc.connect_closing() as board:
        assert handle.sessions.get_messages_as_conversation("same")[0]["content"] == "persistent"
        assert kb.get_task(board, other_task).title == "persist before removal"
        assert plugin_store("discord", namespace="test-wipe").get("same").value == {"persistent": True}


def test_unknown_purge_commit_preserves_local_recovery_files(pg_profiles, monkeypatch):
    from contextlib import contextmanager
    from hermes_cli.data_cleanup import plan_data_removal, remove_data
    from hermes_db.errors import UnknownCommitError
    from hermes_db.infra.postgresql.transactions import Transactions
    with pg_profiles("one") as home:
        seed(home)
        plan = plan_data_removal(home, Path(__file__).resolve().parents[3])
        original = Transactions.write
        @contextmanager
        def lose_ack(self, **kwargs):
            with original(self, **kwargs) as conn:
                yield conn
            raise UnknownCommitError("purge acknowledgement lost; local files must remain")
        with monkeypatch.context() as fault:
            fault.setattr(Transactions, "write", lose_ack)
            with pytest.raises(UnknownCommitError):
                remove_data(plan)
        assert (home / "config.yaml").exists() and (home / ".env").exists()
        # An explicit retry of the same quiescent removal remains idempotent.
        assert remove_data(plan)[1] == []


def test_pg_cron_wipe_probe_reads_running_owner_without_touching_legacy_file(pg_profiles):
    from cron import executions
    from hermes_cli.data_cleanup_holders import _refuse_cron_writers
    with pg_profiles("one") as home:
        row = executions.create_execution("maintenance-proof", source="builtin")
        legacy = home / "cron" / "executions.db"
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_bytes(b"preserve inactive SQLite")
        with pytest.raises(RuntimeError, match="still owns"):
            _refuse_cron_writers(home)
        executions.finish_execution(row["id"], success=True)
        _refuse_cron_writers(home)
        assert legacy.read_bytes() == b"preserve inactive SQLite"


def test_doctor_fix_uses_pg_capability_and_preserves_old_files(pg_profiles, monkeypatch, capsys):
    with pg_profiles("one") as home:
        from hermes_cli import doctor, doctor_state
        monkeypatch.setattr(doctor, "HERMES_HOME", home)
        old = home / "state.db"
        old.write_bytes(b"historical, not active")
        result = doctor_state._check_state_db(True)
        assert result.manual_issues == []
        assert "PostgreSQL system database" in capsys.readouterr().out
        assert old.read_bytes() == b"historical, not active"


def test_removal_plan_rejects_retargeted_store_before_deleting_anything(pg_profiles):
    from hermes_cli.config import atomic_config_write
    from hermes_cli.data_cleanup import plan_data_removal, remove_data
    from hermes_cli.db_setup import open_profile_db
    from hermes_db.errors import StorageConfigurationError
    import hermes_yaml as yaml
    with pg_profiles("two") as other:
        seed(other)
    with pg_profiles("one") as home:
        seed(home)
        original = (home / "config.yaml").read_bytes()
        plan = plan_data_removal(home, Path(__file__).resolve().parents[3])
        replacement = yaml.safe_load(original)
        replacement["storage"]["postgresql"]["store_id"] = "two"
        atomic_config_write(home / "config.yaml", replacement)
        try:
            with pytest.raises(StorageConfigurationError, match="identity changed"):
                remove_data(plan)
            assert (home / "config.yaml").exists() and (home / ".env").exists()
        finally:
            (home / "config.yaml").write_bytes(original)
        with open_profile_db(home) as handle:
            assert handle.sessions.get_messages_as_conversation("same")[0]["content"] == "persistent"
    with pg_profiles("two"), open_profile_db(other) as handle:
        assert handle.sessions.get_messages_as_conversation("same")[0]["content"] == "persistent"
