"""Real PG health, retention, normal Profile lifecycle and local reference fencing."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Event

import pytest

from tests.hermes_db.contracts import test_analytics as analytics
from tests.hermes_db.contracts import test_remaining_read_maintenance as remaining
from tests.hermes_db.contracts import test_retention_selection as retention
from tests.hermes_db.contracts import test_retired_files as files
from tests.hermes_db.contracts import test_storage_health_refs as health

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]

CLOCK = [retention.test_retention_selection_spares_open_pinned_and_recent_message,
    retention.test_old_compression_ancestor_waits_for_current_continuation,
    retention.test_auto_archive_is_scoped_throttled_and_preserves_prompt_history,
    retention.test_orphan_sweep_respects_live_heartbeat_and_turn_lease,
    retention.test_auto_prune_keeps_messaging_open_and_gives_closed_orphan_a_retention_window,
    remaining.test_empty_tui_ghost_pruning_keeps_real_history_and_fresh_rows]
STORE = [retention.test_retention_validates_destructive_bounds_and_escapes_literal_filters,
    health.test_profile_roster_preview_is_bounded_and_skips_tool_rows,
    analytics.test_insights_engine_reports_sessions_tools_and_skills_on_both_backends,
    remaining.test_literal_metadata_and_rich_session_reads,
    remaining.test_anchored_bookends_and_recent_user_turns_keep_the_public_shape,
    remaining.test_kanban_provenance_follows_only_the_verified_compression_chain,
    remaining.test_profile_identity_purge_leaves_session_history_and_other_names]
PAIR = [files.test_core_delayed_spillover_candidate_does_not_unlink_a_replacement,
    health.test_core_storage_identity_and_health_do_not_require_a_local_database_file,
    health.test_core_archive_projection_scope_bound_and_inactive_rows,
    analytics.test_core_dashboard_usage_aggregates_and_source_filter_never_cross_store,
    remaining.test_core_metadata_and_profile_purge_are_scoped_and_terminal_delivery_is_preserved]


@pytest.mark.parametrize("contract", CLOCK, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_maintenance_clock_contracts(pg_store, monkeypatch, contract):
    contract(pg_store, monkeypatch)


@pytest.mark.parametrize("contract", STORE, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_current_store_contracts(pg_store, contract):
    contract(pg_store)


@pytest.mark.parametrize("contract", PAIR, ids=lambda fn: fn.__name__.removeprefix("test_"))
def test_scoped_current_data_contracts(pg_pair, contract):
    contract(pg_pair)








def test_configured_readiness_and_archive_refs_without_local_file(pg_store, postgres_test_config, monkeypatch):
    from hermes_cli import db_setup
    from hermes_db.integration import archive_refs
    from hermes_cli.db_diagnostics import configured_probe
    from hermes_db.settings import DatabaseSettings
    from tools import tool_result_storage as tools
    pg = replace(postgres_test_config.settings, schema=pg_store._transactions.schema)
    monkeypatch.setattr(db_setup, "resolve_db_configuration", lambda home: (DatabaseSettings("postgresql", pg), pg_store.scope))
    monkeypatch.setattr(db_setup, "storage_backend", lambda home: "postgresql")
    root = pg_store.scope.profile_home / "cache" / "spillover"
    root.mkdir(parents=True)
    path = root / "held.txt"
    path.write_text("full output", encoding="utf-8")
    pg_store.create_session("s", "cli")
    pg_store.append_message("s", "user", str(path))
    assert configured_probe(pg_store.scope.profile_home) == {"backend": "postgresql", "status": "ok"}
    assert archive_refs.for_profile(pg_store.scope.profile_home) == (True, {"held.txt"})
    monkeypatch.setattr(tools, "get_spillover_dir", lambda: root)
    assert tools.cleanup_spillover_cache(max_age_hours=-1) == 0 and path.exists()
    assert not (pg_store.scope.profile_home / "state.db").exists()


def test_current_pg_revision_backfills_archive_refs(postgres_test_config, postgres_schema, postgres_engine):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from hermes_db import migrations
    from hermes_db.infra.backends.postgresql.schema import prepare_schema
    from hermes_db.schema import REQUIRED_EXTENSIONS, _PG_TRGM_ACTION, upgrade_schema
    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    directory = Path(migrations.__file__).parent
    config = Config(str(directory / "alembic.ini"))
    config.set_main_option("script_location", str(directory).replace("%", "%%"))
    config.attributes["schema"] = settings.schema
    quoted = postgres_engine.dialect.identifier_preparer.quote(settings.schema)
    with postgres_engine.begin() as conn:
        prepare_schema(conn, settings, required_extensions=REQUIRED_EXTENSIONS,
                       missing_extension_action=_PG_TRGM_ACTION)
        config.attributes["connection"] = conn
        command.upgrade(config, "0002_search_projection")
        conn.exec_driver_sql(f"INSERT INTO {quoted}.transcript_roots(store_id,root_id) VALUES ('owned','s')")
        conn.exec_driver_sql(f"INSERT INTO {quoted}.sessions(store_id,id,lineage_root_id,source,started_at) VALUES ('owned','s','s','cli',1)")
        conn.execute(text(f"INSERT INTO {quoted}.messages(store_id,id,session_id,role,timestamp,content,api_content) "
            "VALUES ('owned',1,'s','user',1,:body,:api)"), {"body": b"Tbefore\x00 spillover/held.txt", "api": b"wire spillover/wire.txt"})
    assert upgrade_schema(settings)["ready"]
    with postgres_engine.connect() as conn:
        names, preview = conn.exec_driver_sql(f"SELECT spillover_names,roster_preview FROM {quoted}.messages WHERE store_id='owned' AND id=1").one()
        assert set(names) == {"held.txt", "wire.txt"}
        assert bytes(preview).decode("utf-8") == "before\x00 spillover/held.txt"




def test_archive_sweep_waits_for_committed_new_reference(pg_store, monkeypatch):
    from sqlalchemy import text
    from hermes_db.integration import archive_refs
    from hermes_db.domains.sessions.postgres.operations.messages import insert_rows
    from hermes_db.domains.sessions.postgres.queries import messages, sessions
    from tests.waiting import wait_until
    pg_store.create_session("s", "cli")
    folder = pg_store.scope.profile_home / "cache" / "spillover"
    folder.mkdir(parents=True)
    path = folder / "new-reference.txt"
    path.write_text("retained output", encoding="utf-8")
    written, waiting, blocked, release = Event(), Event(), Event(), Event()
    waiter_pid = []
    write = pg_store._transactions.write

    @contextmanager
    def traced_write_scope(settings, scope):
        with write() as conn:
            waiter_pid.append(conn.scalar(text("SELECT pg_backend_pid()")))
            waiting.set()
            yield conn

    monkeypatch.setattr(archive_refs, "_write_scope", traced_write_scope)
    health._configured(monkeypatch, pg_store)

    def publish():
        with write() as conn:
            owner = conn.scalar(text("SELECT pg_backend_pid()"))
            sessions.lock_session(conn, pg_store.scope, "s")
            batch = [{"role": "user", "content": str(path)}]
            insert_rows(conn, pg_store.scope, "s", batch)
            messages.bump_counters(conn, pg_store.scope, "s", 1, 0)
            written.set()
            assert waiting.wait(15)
            wait_until(lambda: owner in conn.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid[0]}),
                timeout=5, what="archive cleanup waiting for publication's map fence")
            blocked.set()
            assert release.wait(15)

    def sweep():
        assert written.wait(15)
        return archive_refs.cleanup_if_postgresql(pg_store.scope.profile_home, [path], cutoff=float("inf"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer, cleaner = pool.submit(publish), pool.submit(sweep)
        try:
            assert blocked.wait(15)
        finally:
            release.set()
        writer.result(20)
        assert cleaner.result(20) == 0
    assert path.exists() and pg_store.referenced_spillover_names() == {path.name}
