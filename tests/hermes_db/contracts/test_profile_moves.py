"""Current-store Profile moves preserve exact snapshots and never erase a newer donor."""

from pathlib import Path

import pytest


@pytest.fixture(params=["sqlite", "core"])
def move_pair(request, tmp_path):
    if request.param == "core":
        yield request.getfixturevalue("core_pair")
        return
    from hermes_state import SessionDB
    with SessionDB(db_path=tmp_path / "source" / "state.db") as first, SessionDB(db_path=tmp_path / "target" / "state.db") as second:
        yield first, second


def _populate(store):
    store.create_session("s", "cli", model="model", system_prompt="frozen\x00prompt", model_config={"keep": "exact"})
    store.update_session_tool_names("s", [{"type": "function", "function": {"name": "tool"}}])
    store.append_message("s", "user", "old\x00body")
    mark = store.get_active_message_watermark("s")
    store.append_message("s", "assistant", "late\x00tail", reasoning="reason\x00", api_content="wire\x00")
    store.archive_and_compact("s", [{"role": "user", "content": "summary"}], watermark=mark)
    store.set_session_title("s", "Moved title")
    store.set_session_pinned("s", True)
    store.update_token_counts("s", input_tokens=5, output_tokens=2, model="model")
    store.flush_token_counts()


def test_move_roundtrip_keeps_all_generations_prompts_tool_pins_and_usage(move_pair):
    source, target = move_pair
    _populate(source)
    payload = source.export_session_for_move("s")
    assert target.import_moved_session(payload, profile_name="target") == "imported"
    assert target.import_moved_session(payload, profile_name="target") == "present"
    before = source.get_messages("s", include_inactive=True)
    after = target.get_messages("s", include_inactive=True)
    ignored = {"id", "display_order"}
    assert [{k: v for k, v in row.items() if k not in ignored} for row in after] == [
        {k: v for k, v in row.items() if k not in ignored} for row in before]
    assert target.get_session("s")["system_prompt"] == "frozen\x00prompt"
    assert target.get_session("s")["tool_names"] == source.get_session("s")["tool_names"]
    assert target.get_session("s")["profile_name"] == "target" and target.get_session("s")["pinned"] == 1
    assert target.get_session("s")["input_tokens"] == 5
    assert source.delete_moved_session("s") and source.get_session("s") is None
    assert target.get_messages("s", include_inactive=True) == after


def test_core_move_refuses_unrelated_resident_id_and_stale_source_snapshot(core_pair):
    from hermes_state_runtime import RuntimeStoreError
    source, target = core_pair
    source.create_session("s", "cli")
    source.append_message("s", "user", "donor")
    target.create_session("s", "cli")
    target.append_message("s", "user", "resident")
    payload = source.export_session_for_move("s")
    with pytest.raises(RuntimeStoreError, match="session_exists|conflict"):
        target.import_moved_session(payload, profile_name="target")
    assert source.get_messages("s")[0]["content"] == "donor"
    source.create_session("growing", "cli")
    source.append_message("growing", "user", "first donor work")
    target.import_moved_session(source.export_session_for_move("growing"), profile_name="target")
    source.append_message("growing", "assistant", "new donor work")
    with pytest.raises(RuntimeStoreError, match="changed|stale"):
        source.delete_moved_session("growing")
    assert len(source.get_messages("growing")) == 2 and target.get_messages("s")[0]["content"] == "resident"


def test_core_move_keeps_source_owned_spillover_after_donor_retirement(core_pair):
    from hermes_db.health import profile_home_for_store
    source, target = core_pair
    folder = profile_home_for_store(source) / "cache" / "spillover"
    folder.mkdir(parents=True)
    path = folder / "moved.txt"
    path.write_text("full tool output", encoding="utf-8")
    source.create_session("s", "cli")
    source.append_message("s", "tool", f"Full output saved to: {path}")
    assert target.import_moved_session(source.export_session_for_move("s"), profile_name="target") == "imported"
    assert source.delete_moved_session("s")
    source.collect_retired_media()
    assert path.exists() and source.referenced_spillover_names() == {"moved.txt"}
    assert str(Path(path)) in target.get_messages("s")[0]["content"]


def test_core_pg_move_rejects_sqlite_snapshot_and_ledgered_source(core_pair, tmp_path):
    from hermes_db.errors import StorageConfigurationError
    from hermes_db.runtime_store import PostgresRuntimeStore
    import pickle
    import subprocess
    import sys
    from tests.gateway.fixtures.local_recovery_probe import child_env
    from hermes_state_profile_repair import SessionLedgeredError
    source, target = core_pair
    # A real user-owned SQLite input is created in its own process, outside the PG business guard.
    script = """
import pathlib, pickle, sys
from hermes_state import SessionDB
root = pathlib.Path(sys.argv[1])
with SessionDB(db_path=root / 'legacy.db') as db:
    db.create_session('sqlite', 'cli')
    db.append_message('sqlite', 'user', 'old SQLite data')
    (root / 'input-snapshot').write_bytes(pickle.dumps(db.export_session_for_move('sqlite')))
"""
    child_home = tmp_path / "sqlite-input-home"
    child_home.mkdir()
    environment = dict(child_env(), HOME=str(child_home), USERPROFILE=str(child_home), HERMES_HOME=str(child_home),
        HERMES_RUNTIME_DIR=str(child_home / "runtime"))
    process = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=environment,
        capture_output=True, text=True, timeout=60, check=False)
    assert process.returncode == 0, process.stderr
    snapshot = pickle.loads((tmp_path / "input-snapshot").read_bytes())
    with pytest.raises(StorageConfigurationError, match="PostgreSQL|PG"):
        target.import_moved_session(snapshot, profile_name="target")
    source.create_session("live", "cli")
    runtime = PostgresRuntimeStore(source)
    epoch = runtime.begin_epoch(instance_id="owner")
    runtime.admit_input(epoch=epoch, principal_id="owner", session_id="live", request_id="r", payload={"text": "held"})
    with pytest.raises(SessionLedgeredError):
        source.export_session_for_move("live")


def _move_file(source, target, filename="shared.txt"):
    folder = source.scope.profile_home / "cache" / "spillover"
    folder.mkdir(parents=True)
    path = folder / filename
    path.write_text("exact full output", encoding="utf-8")
    source.create_session("s", "cli")
    source.append_message("s", "tool", f"Full output saved to: {path}")
    target.import_moved_session(source.export_session_for_move("s"), profile_name="target")
    source.delete_moved_session("s")
    return path


def test_core_moved_file_lives_until_last_recipient_history_is_deleted(core_pair):
    source, target = core_pair
    path = _move_file(source, target)
    branch = target.export_session("s", include_inactive=True)
    branch.update(id="fork", parent_session_id=None, title=None)
    assert target.import_sessions([branch])["imported"] == 1
    assert target.delete_session("s") and path.exists()
    assert target.delete_session("fork")
    assert not path.exists() and source.referenced_spillover_names() == set()


def test_core_file_grant_follows_a_second_move_without_moving_file_bytes(core_pair, tmp_path):
    from hermes_db.scope import DatabaseScope
    from hermes_db.domains.sessions.postgres.store import PostgresSessionStore
    source, middle = core_pair
    path = _move_file(source, middle)
    final = PostgresSessionStore(source._transactions, DatabaseScope(tmp_path / "final", "final"))
    try:
        final.import_moved_session(middle.export_session_for_move("s"), profile_name="final")
        assert middle.delete_moved_session("s") and path.exists()
        assert final.delete_session("s")
        assert not path.exists() and source.referenced_spillover_names() == set()
    finally:
        final.close()


def test_core_parent_first_retirement_keeps_child_snapshot_valid(core_pair):
    source, target = core_pair
    source.create_session("root", "cli")
    source.append_message("root", "user", "head")
    source.end_session("root", "compression")
    source.create_session("tip", "cli", parent_session_id="root")
    source.append_message("tip", "assistant", "tail")
    payloads = [source.export_session_for_move(sid) for sid in ("root", "tip")]
    for payload in payloads:
        assert target.import_moved_session(payload, profile_name="target") == "imported"
    assert source.delete_moved_session("root")
    assert source.delete_moved_session("tip")
    assert target.get_session("tip")["parent_session_id"] == "root"
    assert [row["content"] for row in target.get_messages_as_conversation("tip", include_ancestors=True)] == ["head", "tail"]


def test_core_grant_creation_rolls_back_with_target_copy_and_unknown_ack_replays_receipt(core_pair, monkeypatch):
    from contextlib import contextmanager
    from hermes_db.errors import UnknownCommitError
    from hermes_db.domains.sessions.postgres.queries import file_grants
    source, target = core_pair
    folder = source.scope.profile_home / "cache" / "spillover"
    folder.mkdir(parents=True)
    path = folder / "atomic.txt"
    path.write_text("full output", encoding="utf-8")
    source.create_session("s", "cli")
    source.append_message("s", "tool", str(path))
    payload = source.export_session_for_move("s")
    put = file_grants.put

    def fail_recipient(conn, scope, key, value):
        if key.startswith(file_grants.RECEIVED):
            raise RuntimeError("injected recipient write failure")
        return put(conn, scope, key, value)

    with monkeypatch.context() as patch:
        patch.setattr(file_grants, "put", fail_recipient)
        with pytest.raises(RuntimeError, match="recipient"):
            target.import_moved_session(payload, profile_name="target")
    assert target.get_session("s") is None and path.exists()
    with source._read() as conn:
        assert file_grants.rows(conn, source.scope, file_grants.OWNED) == []
    original_write = target._write

    @contextmanager
    def lost_ack():
        with original_write() as conn:
            yield conn
        raise UnknownCommitError("injected commit acknowledgement loss")

    with monkeypatch.context() as patch:
        patch.setattr(target, "_write", lost_ack)
        with pytest.raises(UnknownCommitError):
            target.import_moved_session(payload, profile_name="target")
    assert source.get_session("s") is not None
    assert target.import_moved_session(payload, profile_name="target") == "present"
    with source._read() as conn:
        assert len(file_grants.rows(conn, source.scope, file_grants.OWNED)) == 1
    assert source.delete_moved_session("s") and path.exists()
    assert target.delete_session("s") and not path.exists()
