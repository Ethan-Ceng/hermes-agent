"""Existing SQLite domain reads never create or migrate their stores."""

import re
import sqlite3

import pytest

from hermes_db.errors import StorageSchemaError


def test_cron_reads_after_explicit_job_creation_do_not_run_ddl(tmp_path, monkeypatch):
    from cron import delivery_queue, executions, incidents, jobs, notepad

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    job_id = jobs.create_job(prompt="ordinary query", schedule="every 1h")["id"]
    execution_id = executions.create_execution(job_id, source="test")["id"]
    incident_id, _ = incidents.upsert_incident(job_id, "fixture failure")
    notepad.set_note(job_id, "cursor", "retained")
    delivery_queue.enqueue(execution_id, {"id": job_id}, "fixture delivery")

    trace = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    jobs.create_job(prompt="second normal job", schedule="every 2h")
    assert executions.get_execution(execution_id)["job_id"] == job_id
    assert incidents.get_incident(incident_id)["job_id"] == job_id
    assert notepad.get_note(job_id, "cursor") == "retained"
    assert delivery_queue.get_status(execution_id)["status"] == "pending"
    assert trace
    assert not [sql for sql in trace if re.match(r"\s*(?:CREATE|ALTER|DROP|REINDEX)\b", sql, re.IGNORECASE)]


def test_uninitialized_projects_connection_leaves_path_absent(tmp_path):
    from hermes_cli.projects_db import connect_closing

    path = tmp_path / "projects.db"
    with pytest.raises(StorageSchemaError, match="hermes db upgrade"):
        with connect_closing(path, profile_home=tmp_path):
            pytest.fail("an uninitialized projects store was opened")
    assert not path.exists()


def test_empty_room_listing_does_not_initialize_shared_store(tmp_path, monkeypatch):
    from gateway.hosted_rooms import list_rooms

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "shared-state.db"
    assert list_rooms(path) == []
    assert not path.exists()


def test_explicit_metrics_enable_then_ordinary_open_has_no_ddl(tmp_path, monkeypatch, capsys):
    from hermes_cli.config import set_config_value
    from hermes_cli.observability.shared_metrics import SharedMetricsStore

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    set_config_value("telemetry.shared_metrics.enabled", "true")
    capsys.readouterr()
    trace = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    store = SharedMetricsStore(profile_home=tmp_path)
    store.reconcile_send_consent(False)
    assert trace
    assert not [sql for sql in trace if re.match(r"\s*(CREATE|ALTER|DROP|REINDEX)\b", sql, re.IGNORECASE)]


def test_session_only_store_can_start_room_service_without_ddl(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gateway import hosted_rooms
    from hermes_state import SessionDB
    from tui_gateway.hosted_room_service import HostedRoomService

    path = tmp_path / "state.db"
    SessionDB(path).close()
    trace = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced)
    service = HostedRoomService(SimpleNamespace(_methods={}, _sessions={}), db_path=path)
    assert hosted_rooms.list_rooms(path) == []
    assert not [sql for sql in trace if re.match(r"\s*(CREATE|ALTER|DROP|REINDEX)\b", sql, re.IGNORECASE)]
    service.local_profiles = lambda: ("default", "ops")
    service.create_room(room_id="first", name="first", members=[
        {"member_id": "default", "profile": "default", "handle": "default"}, {"member_id": "ops", "profile": "ops", "handle": "ops"},
    ])
    assert hosted_rooms.room_state(path, room_id="first")["name"] == "first"


def test_partial_cron_initialization_cannot_publish_a_job_on_retry(tmp_path, monkeypatch):
    from cron import incidents, jobs
    from cron.storage_lifecycle import initialize_cron_stores

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    def interrupted():
        raise RuntimeError("interrupted after execution schema creation")

    with monkeypatch.context() as change:
        change.setattr(incidents, "initialize", interrupted)
        with pytest.raises(RuntimeError, match="interrupted"):
            jobs.create_job(prompt="interrupted first create", schedule="every 1h")
    assert jobs.load_jobs() == []
    with pytest.raises(StorageSchemaError):
        jobs.create_job(prompt="retry against partial schema", schedule="every 1h")
    assert jobs.load_jobs() == []
    initialize_cron_stores()
    restored = jobs.create_job(prompt="explicitly restored", schedule="every 1h")
    assert [job["id"] for job in jobs.load_jobs()] == [restored["id"]]


def test_room_queries_validate_main_schema_and_components_validate_on_acquisition(tmp_path, monkeypatch):
    from gateway import hosted_rooms
    from gateway.hosted_room_attachments import HostedRoomAttachmentStore

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "shared-state.db"
    hosted_rooms.create_room(path, room_id="main", name="Main schema", members=[
        {"member_id": "one", "profile": "one", "handle": "one"},
        {"member_id": "two", "profile": "two", "handle": "two"},
    ], authority_gateway_id=hosted_rooms.local_authority_gateway_id())
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE hosted_room_attachments")
    assert hosted_rooms.room_state(path, room_id="main")["room_id"] == "main"
    with pytest.raises(StorageSchemaError):
        HostedRoomAttachmentStore(path)
