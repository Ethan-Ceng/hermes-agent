"""Current export/import payloads preserve history and reset live ownership state."""

import json


def test_current_export_roundtrip_preserves_archived_rows_uid_and_prompt(store):
    store.create_session("s", "cli", model="m", system_prompt="exact\x00prefix", session_key="route", chat_id="chat")
    store.set_session_pinned("s", True)
    store.set_session_title("s", "Original")
    store.touch_session_activity("s", description="working", provenance="agent")
    store.append_message("s", "user", "old\x00")
    store.archive_and_compact("s", [{"role": "user", "content": "summary", "_compressed_summary": True}])
    payload = store.export_session("s", include_inactive=True)
    assert len(payload["messages"]) == 2 and payload["timings"]["message_timestamps"]["available"] == 2
    payload.update(id="copy", title="Copied")
    result = store.import_sessions([payload])
    assert result["ok"] and result["imported_ids"] == ["copy"]
    row = store.get_session("copy")
    assert row["system_prompt"] == "exact\x00prefix" and row["pinned"]
    assert row["session_key"] is None and row["chat_id"] is None and row["last_activity_at"] is None
    old, copied = payload["messages"], store.get_messages("copy", include_inactive=True)
    assert [(m["content"], m["message_uid"], m["active"], m["compacted"]) for m in copied] == [(m["content"], m["message_uid"], m["active"], m["compacted"]) for m in old]
    assert store.get_session("copy")["message_count"] == 1
    assert store.import_sessions([payload])["skipped_ids"] == ["copy"]


def test_import_validates_whole_batch_and_refuses_retired_ids_without_partial_rows(store):
    assert not store.import_sessions([{"id": "first", "messages": []}, {"id": "bad", "messages": [{"role": "user", "content": float("inf")}]}])["ok"]
    assert store.get_session("first") is None
    store.create_session("retired", "cli")
    store.delete_session("retired")
    result = store.import_sessions([{"id": "first", "messages": []}, {"id": "retired", "messages": []}])
    assert not result["ok"] and store.get_session("first") is None


def test_import_parent_graph_detaches_cycle_and_preserves_independent_fork_root(store):
    result = store.import_sessions([
        {"id": "root", "source": "cli", "parent_session_id": "child", "end_reason": "compression", "messages": []},
        {"id": "child", "source": "cli", "parent_session_id": "root", "messages": []},
        {"id": "branch", "source": "cli", "parent_session_id": "root", "model_config": json.dumps({"_branched_from": "root"}), "messages": []}])
    assert result["ok"] and result["detached"] == 1
    assert store.get_session("root")["parent_session_id"] is None
    assert store.get_session("child")["parent_session_id"] == "root"
    assert store.get_compression_lineage("child") == ["root", "child"]
    assert store.get_compression_lineage("branch") == ["branch"]


def test_foreign_snapshot_import_is_idempotent_and_scaffold_workspace_reads_are_scoped(store):
    from agent.skill_commands import SKILL_SCAFFOLD_SQL_LIKE

    origin = {"tool": "foreign", "foreign_session_id": "f", "path": "/source"}
    args = dict(title="Imported", cwd="/workspace", profile="owned")
    first = store.import_foreign_history(origin, [{"role": "user", "content": SKILL_SCAFFOLD_SQL_LIKE[:-1] + '"skill" body'}], **args)
    second = store.import_foreign_history(origin, [{"role": "user", "content": "changed snapshot"}], **args)
    assert first["session_id"] == second["session_id"] and second["already_imported"]
    assert store.find_foreign_import(origin) == first["session_id"]
    assert store.distinct_session_cwds()[0]["cwd"] == "/workspace"
    rows = store.list_skill_scaffolded_sessions()
    assert len(rows) == 1 and rows[0]["id"] == first["session_id"]
    assert store.list_skill_scaffolded_sessions(limit=0) == []
    assert store.export_all(source="foreign")[0]["id"] == first["session_id"]


def test_current_cron_admissions_keep_exact_job_identity(store, runtime):
    from hermes_state_keys import CRON_PRINCIPAL_ID
    epoch = runtime.begin_epoch(instance_id="owner")
    for sid, job in [("one", "job"), ("other", "job-other")]:
        store.create_session(sid, "cron")
        runtime.admit_input(epoch=epoch, principal_id=CRON_PRINCIPAL_ID, session_id=sid, request_id=f"cron:{job}:execution", payload={})
    assert store.cron_run_identity("one") == {"cron_job_id": "job", "cron_execution_id": "execution"}
    assert [row["id"] for row in store.list_cron_job_runs("job")] == ["one"]
