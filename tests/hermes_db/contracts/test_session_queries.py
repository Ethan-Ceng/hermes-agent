"""Visibility, filtering, paging and lineage projection are business contracts."""


def test_list_count_source_scope_and_hidden_archive_recovery(store):
    store.create_session("cli", source="cli", cwd="/work/a")
    store.create_session("local-cli", source="local", cwd="/work/a")
    store.create_session("local-tool", source="local", cwd="/work/a")
    # The creator upsert fills local routing rows' actual surface provenance.
    store.create_session("local-cli", source="cli")
    store.create_session("local-tool", source="tool")
    scoped = store.list_sessions_rich(sources=["local"], local_created_sources=["cli"])
    assert [row["id"] for row in scoped] == ["local-cli"]
    assert store.session_count(sources=["local"], local_created_sources=["cli"]) == 1
    store.set_session_hidden("cli", True)
    assert "cli" not in {row["id"] for row in store.list_sessions_rich()}
    store.set_session_archived("cli", True, notify=False)
    assert "cli" in {row["id"] for row in store.list_sessions_rich(archived_only=True)}


def test_compression_projection_keeps_root_ordering_and_tip_identity(store):
    store.create_session("root", source="cli", cwd="/a")
    store.set_session_title("root", "remember")
    started = store.get_session("root")["started_at"]
    store.end_session("root", "compression")
    store.create_session("tip", source="cli", parent_session_id="root", model="new")
    rows = store.list_sessions_rich(order_by_last_active=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "tip"
    assert row["started_at"] == started
    assert row["title"] == "remember"
    assert row["_lineage_root_id"] == "root"
    assert set(row["_lineage_ids"]) == {"root", "tip"}
    assert store.session_count(exclude_children=True) == 1


def test_literal_prefixes_workspace_filters_and_pinned_backfill(store):
    for session_id, cwd in (("literal_%", "/path_%/a"), ("literal-ab", "/path-other/a"), ("last", "/z")):
        store.create_session(session_id, source="cli", cwd=cwd)
    assert store.resolve_session_id("literal_%") == "literal_%"
    assert store.resolve_session_id("literal-") == "literal-ab"
    assert store.resolve_session_id("literal") is None
    assert [row["id"] for row in store.list_sessions_rich(cwd_prefix="/path_%")] == ["literal_%"]
    assert [row["id"] for row in store.search_sessions(workspace_key="/path_%")] == ["literal_%"]
    store.set_session_pinned("literal_%", True)
    store.set_session_archived("literal_%", True, notify=False)
    ids = [row["id"] for row in store.list_sessions_rich(limit=1, include_pinned=True)]
    assert "last" in ids and "literal_%" in ids


def test_list_search_normalization_and_model_key_scan(store):
    store.create_session("s", source="cli", model_config={"a": {"b": 1}})
    store.set_session_title("s", "AN-94")
    assert [row["id"] for row in store.list_sessions_rich(order_by_last_active=True, search_query="an94")] == ["s"]
    assert store.session_ids_with_model_config_key("a.b") == ["s"]


def test_origin_lookup_never_selects_another_sender(store):
    store.create_session("one", source="telegram", chat_id="c", user_id="u1", session_key="key1")
    store.create_session("two", source="telegram", chat_id="c", user_id="u2", session_key="key2")
    assert store.find_session_by_origin(platform="TELEGRAM", chat_id="c") is None
    assert store.find_session_by_origin(platform="telegram", chat_id="c", user_id="u1") == "one"
    assert store.find_session_by_origin(platform="telegram", chat_id="c", user_id="unknown") is None


def test_late_parent_fill_joins_an_empty_placeholder_to_its_compression_lineage(store):
    store.create_session("root", source="cli")
    store.end_session("root", "compression")
    store.ensure_session("tip")
    store.create_session("tip", source="cli", parent_session_id="root")
    store.set_session_hidden("tip", True)
    assert store.get_session("root")["hidden"] == 1
