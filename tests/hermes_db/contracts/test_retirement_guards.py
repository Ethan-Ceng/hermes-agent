"""Delete/export selection must include durable history and the exact cascade."""

import pytest


def test_export_bound_counts_archived_rows_as_well_as_active_context(store):
    from hermes_state import SessionExportTooLargeError

    store.create_session("s", "test")
    for index in range(3):
        store.append_message("s", "user", str(index))
    store.archive_and_compact("s", [{"role": "user", "content": "summary"}])
    assert store.assert_export_safe("s", max_messages=4) == 4
    assert store.assert_export_safe("s", max_messages=0) == 0
    with pytest.raises(SessionExportTooLargeError):
        store.assert_exports_safe(["s"], max_messages=3)


def test_native_delete_target_probe_includes_delegates_but_not_other_conversations(store):
    store.create_session("root", "cli")
    store.create_session("delegate", "delegate", parent_session_id="root", model_config={"_delegate_from": "root"})
    store.end_session("delegate", "compression")
    store.create_session("delegate-tip", "delegate", parent_session_id="delegate", model_config={"_delegate_from": "root"})
    store.end_session("root", "compression")
    store.create_session("continuation", "cli", parent_session_id="root")
    store.create_session("branch", "cli", parent_session_id="root", model_config={"_branched_from": "root"})
    assert set(store.get_session_delete_targets("root")) == {"root", "delegate", "delegate-tip"}
    assert store.get_session_delete_targets("absent") == []


def test_core_delete_probe_is_scoped_even_with_same_parent_marker(core_pair):
    first, second = core_pair
    for store in core_pair:
        store.create_session("root", "cli")
    second.create_session("foreign", "delegate", parent_session_id="root", model_config={"_delegate_from": "root"})
    assert first.get_session_delete_targets("root") == ["root"]
    assert set(second.get_session_delete_targets("root")) == {"root", "foreign"}
