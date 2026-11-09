"""Retired local files stay while a surviving row or accepted input owns them."""

from pathlib import Path


def test_core_spillover_cleanup_keeps_shared_branch_pointer_until_last_owner(core_pair):
    store, other = core_pair
    spill = store.scope.profile_home / "cache" / "spillover"
    spill.mkdir(parents=True)
    archive = spill / "result.txt"
    archive.write_text("full result", encoding="utf-8")
    for sid in ("original", "branch"):
        store.create_session(sid, "cli")
        store.append_message(sid, "tool", 'pointer\x00 ' + str(archive), tool_call_id="call")
    other.create_session("other", "cli")
    other.append_message("other", "user", "another store")
    store.delete_session("original")
    assert archive.exists()
    store.delete_session("branch")
    assert not archive.exists()


def test_core_retired_media_keeps_live_input_then_releases_under_own_profile(core_pair):
    import hashlib
    from hermes_db.integration.runtime_composition import create_runtime_store
    from gateway.session_ingress_media import native_inputs_root

    store, other = core_pair
    with store._profile.activate():
        root = native_inputs_root()
    digest = hashlib.sha256(b"media").hexdigest()
    path = root / digest / "note.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"media")
    reference = {"path": str(path), "sha256": digest}
    runtime = create_runtime_store(store)
    epoch = runtime.begin_epoch(instance_id="owner")
    for sid in ("retired", "held"):
        store.create_session(sid, "cli")
        row = runtime.admit_input(epoch=epoch, principal_id="human", session_id=sid, request_id=sid,
            payload={"attachments_v1": {"media": [reference]}})
        if sid == "retired":
            runtime.cancel_input(epoch=epoch, admission_id=row["admission_id"])
    with other._profile.activate():
        store.delete_session("retired")
    assert path.exists()
    runtime.cancel_input(epoch=epoch, admission_id=row["admission_id"])
    store.delete_session("held")
    assert not path.exists()
    assert not Path(other.scope.profile_home / "cache" / "documents").exists()


def test_core_delayed_spillover_candidate_does_not_unlink_a_replacement(core_pair):
    store = core_pair[0]
    root = store.scope.profile_home / "cache" / "spillover"
    root.mkdir(parents=True)
    path = root / "reused.txt"
    path.write_text("original", encoding="utf-8")
    for sid in ("one", "two"):
        store.create_session(sid, "cli")
        store.append_message(sid, "tool", str(path))
    store.delete_session("one")
    path.unlink()
    path.write_text("fresh replacement with another identity", encoding="utf-8")
    store.delete_session("two")
    assert path.read_text(encoding="utf-8") == "fresh replacement with another identity"
