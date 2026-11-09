"""Original SQLite corpus and pure PG search planning, without claiming PG execution."""

import pytest

from tests.hermes_db.contracts import search_corpus


@pytest.fixture
def reference(tmp_path):
    from hermes_state import SessionDB
    with SessionDB(db_path=tmp_path / "search.db") as store:
        yield store


def test_multilingual_recall_contract(reference):
    search_corpus.recall_contract(reference)


def test_search_filter_and_projection_contract(reference):
    search_corpus.filter_contract(reference)


def test_pg_plan_preserves_boolean_phrase_prefix_and_zero_hit_relaxation():
    from hermes_db.domains.sessions.postgres.support.search_query import parse_query
    plan = parse_query('alpha AND "docker networking" OR beta NOT gamma')
    assert plan.groups == ((("alpha", False, False), ("docker networking", False, False)),
        (("beta", False, False), ("gamma", False, True)))
    assert plan.relaxed is None
    assert parse_query("when does Sarah like standup").relaxed == "when OR does OR Sarah OR like OR standup"
    assert parse_query("networ*").groups == ((("networ", True, False),),)
    assert parse_query("桂林 连接").relaxed is None
    assert parse_query('"unterminated').groups == ((("unterminated", False, False),),)


def test_pg_projection_bounds_tool_index_and_indexes_short_terms_without_mutating_content():
    from hermes_db.domains.sessions.postgres.support.search_projection import projection
    from hermes_state_common import FTS_TOOL_CONTENT_PREFIX_CHARS
    original = "你\x00好AI" + "x" * FTS_TOOL_CONTENT_PREFIX_CHARS + "tailneedle"
    document, grams = projection(dict(content=original, role="tool", tool_name="terminal", tool_calls=None))
    assert "tailneedle" not in document and "terminal" in document
    assert {"你", "好", "你好", "ai"} <= set(grams)
    assert "\x00" not in document and "\x00" in original
    assert "tailneedle" in projection(dict(content=original, role="user"))[0]
    from hermes_db.domains.sessions.postgres.support.search_projection import content_text
    assert "工具JSON桂林" in content_text({"content": [{"type": "text", "text": "工具JSON桂林"}]})


def test_core_prune_updates_search_projection_and_never_exports_derived_fields(core_pair):
    from sqlalchemy import select
    from hermes_db.tables.conversations import messages
    store = core_pair[0]
    store.create_session("s", "cli")
    store.append_message("s", "assistant", "旧数据库\x00body")
    original = store.get_messages_as_conversation("s", include_row_ids=True)[0]
    store.rewrite_pruned_rows("s", [(original, {**original, "content": "新连接池\x00body"})])
    with store._read() as conn:
        rows = conn.execute(select(messages.c.search_document, messages.c.search_grams).where(
            messages.c.store_id == store.scope.store_id, messages.c.session_id == "s")).all()
    assert {row[0] for row in rows} == {"旧数据库body", "新连接池body"}
    assert all(row[1] and "body" not in row[1] for row in rows)
    assert all("search_document" not in row and "search_grams" not in row for row in store.get_messages("s", include_inactive=True))


def test_search_sql_binds_untrusted_terms_and_keeps_store_filter(tmp_path):
    pytest.importorskip("sqlalchemy", reason="optional postgresql extra")
    from sqlalchemy.dialects import postgresql
    from hermes_db.backends.postgresql.search import statement
    from hermes_db.scope import DatabaseScope
    from hermes_db.domains.sessions.postgres.support.search_query import parse_query
    for route in ("fts", "substring"):
        query = statement(DatabaseScope(tmp_path, "owned-store"), parse_query('"桂林%_\' DROP TABLE messages;"'), route=route)
        compiled = query.compile(dialect=postgresql.dialect())
        assert "owned-store" in compiled.params.values()
        assert "DROP TABLE" not in str(compiled)
        assert any("drop table" in str(value).lower() for value in compiled.params.values())


def test_core_search_context_uses_scoped_ids_even_when_physical_ids_collide(core_pair):
    from hermes_db.domains.sessions.postgres.queries import search_context
    from hermes_db.tables.conversations import messages
    first, other = core_pair
    for store in core_pair:
        store.create_session("same", "cli")
    row_id = first.append_message("same", "user", "owned context")
    other.append_message("same", "user", "foreign context")
    with other._write() as conn:
        conn.execute(messages.update().where(messages.c.store_id == other.scope.store_id).values(id=row_id))
    matches = [{"id": row_id}]
    with first._read() as conn:
        search_context.attach(conn, first.scope, matches)
    assert matches == [{"id": row_id, "context": [{"role": "user", "content": "owned context"}]}]


def test_core_search_rejects_unknown_projection_before_querying(core_pair):
    with pytest.raises(ValueError, match="unknown search"):
        core_pair[0].search_messages("", fields=["secret"])
    with pytest.raises(TypeError, match="collection"):
        core_pair[0].search_messages("", fields="context")
