"""Real PG multilingual recall, projections, chunk limits and query-plan evidence."""

import json
import time

import pytest

from tests.hermes_db.contracts import search_corpus
from tests.hermes_db.contracts.test_search import test_core_prune_updates_search_projection_and_never_exports_derived_fields as prune_contract

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.mark.parametrize("contract", [search_corpus.recall_contract, search_corpus.filter_contract], ids=lambda fn: fn.__name__)
def test_search_corpus_on_postgresql(pg_store, contract):
    contract(pg_store)


def test_search_prune_projection_on_postgresql(pg_pair):
    prune_contract(pg_pair)


def test_search_scope_context_literal_and_boolean_isolation(pg_pair):
    first, other = pg_pair
    for store in (first, other):
        store.create_session("same", "cli")
    first.append_message("same", "user", "完成率100%_ok的桂林查询")
    other.append_message("same", "user", "private 完成率100%_ok 桂林")
    first.append_message("same", "assistant", "完成率100XXok的普通查询")
    matches = first.search_messages("完成率100%_ok")
    assert len(matches) == 1 and "private" not in json.dumps(matches)
    assert first.search_messages("桂林 NOT 查询") == []
    assert first.search_messages("桂林 OR absent")
    assert first.search_messages("absent NOT 桂林") == []


def test_tool_search_prefix_and_explicit_full_body_on_postgresql(pg_store):
    from hermes_state_common import FTS_TOOL_CONTENT_PREFIX_CHARS
    pg_store.create_session("s", "cli")
    pg_store.append_message("s", "tool", "prefixneedle " + "x " * FTS_TOOL_CONTENT_PREFIX_CHARS + "tailneedle 中文尾部", tool_name="terminal")
    assert pg_store.search_messages("prefixneedle")
    assert pg_store.search_messages("tailneedle") == []
    matches = pg_store.search_messages("tailneedle", role_filter=["tool"])
    assert matches and "tailneedle" in matches[0]["snippet"]
    assert pg_store.search_messages("中文尾部", role_filter=["tool"])
    pg_store.append_message("s", "tool", [{"type": "text", "text": "工具JSON桂林"}], tool_name="terminal")
    assert pg_store.search_messages("工具JSON桂林", role_filter=["tool"])


def test_search_inactive_compacted_and_clone_visibility_on_postgresql(pg_store):
    pg_store.create_session("s", "cli")
    pg_store.append_message("s", "user", "archivedneedle")
    mark = pg_store.get_active_message_watermark("s")
    pg_store.append_message("s", "assistant", "lateclone")
    pg_store.archive_and_compact("s", [{"role": "user", "content": "summaryneedle"}], watermark=mark)
    assert pg_store.search_messages("archivedneedle")
    # A carried tail's old physical copy is rewound (active=0,compacted=0),
    # while its clone's trigger created its own scoped search chunks.
    assert len(pg_store.search_messages("lateclone")) == 1
    assert len(pg_store.search_messages("lateclone", include_inactive=True)) == 2


def test_large_unique_message_and_late_repeated_phrase_do_not_break_persistence(pg_store):
    pg_store.create_session("large", "cli")
    body = " ".join(f"unique{index:08d}" for index in range(100000)) + " " + "a " * 5000 + "distinctive"
    row_id = pg_store.append_message("large", "user", body)
    assert row_id and pg_store.get_messages("large")[0]["content"] == body
    assert pg_store.search_messages("unique00099999")
    assert pg_store.search_messages('"a distinctive"')
    pg_store.create_session("other", "cli")
    pg_store.append_message("other", "user", "unique00000000")
    assert len(pg_store.search_messages("unique00000000 OR unique00099999")) == 2


def test_failed_message_operation_rolls_back_derived_chunks(pg_store, monkeypatch):
    from sqlalchemy import func, select
    from hermes_db.domains.sessions.postgres.queries import messages as repo
    from hermes_db.tables.conversations import message_search_chunks, messages
    pg_store.create_session("s", "cli")
    original = repo.insert_row

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected post-trigger failure")

    with monkeypatch.context() as patch:
        patch.setattr(repo, "insert_row", fail_after_insert)
        with pytest.raises(RuntimeError, match="post-trigger"):
            pg_store.append_message("s", "user", "rolled back search")
    with pg_store._read() as conn:
        for table in (messages, message_search_chunks):
            assert conn.scalar(select(func.count()).select_from(table).where(table.c.store_id == pg_store.scope.store_id)) == 0


def test_search_plan_and_index_size_evidence(pg_store, tmp_path, record_property):
    from sqlalchemy import func, select, text
    from hermes_db.domains.sessions.postgres.support.search import statement
    from hermes_db.domains.sessions.postgres.support.search_query import parse_query
    from hermes_db.tables.conversations import messages

    pg_store.create_session("scale", "cli")
    rows = [{"role": "user", "content": f"ordinary document number {index:05d}"} for index in range(10000)]
    rows[9000]["content"] += " 稀龘 桂林 uniqueprobe"
    started = time.monotonic()
    pg_store.append_messages_batch("scale", rows)
    insert_seconds = time.monotonic() - started
    schema = pg_store._transactions.schema
    quoted = pg_store._transactions.engine.dialect.identifier_preparer.quote(schema)
    with pg_store._write() as conn:
        conn.exec_driver_sql(f"ANALYZE {quoted}.messages")
        conn.exec_driver_sql(f"ANALYZE {quoted}.message_search_chunks")
    evidence = {"insert_seconds": insert_seconds, "queries": {}}
    with pg_store._read() as conn:
        evidence["server_version"] = conn.scalar(text("SHOW server_version"))
        evidence["rows"] = conn.scalar(select(func.count()).select_from(messages).where(messages.c.store_id == pg_store.scope.store_id))
        evidence["indexes"] = [dict(row) for row in conn.execute(text("SELECT indexname,pg_relation_size((quote_ident(schemaname)||'.'||quote_ident(indexname))::regclass) AS bytes "
            "FROM pg_indexes WHERE schemaname=:schema AND tablename IN ('messages','message_search_chunks')"), {"schema": schema}).mappings()]
        for query, route in (("龘", "substring"), ("桂林", "substring"), ("uniqueprobe", "fts")):
            sql = statement(pg_store.scope, parse_query(query), route=route).compile(dialect=conn.dialect,
                schema_translate_map=conn.get_execution_options()["schema_translate_map"], compile_kwargs={"literal_binds": True}, render_schema_translate=True)
            evidence["queries"][query] = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(sql)).scalar_one()
    path = tmp_path / "search-evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    record_property("search_evidence", str(path))
    assert evidence["rows"] == 10000
    assert "ix_messages_search_grams" in json.dumps(evidence["queries"]["龘"])


def test_current_pg_revision_backfills_search_and_chunks_atomically(postgres_test_config, postgres_schema, postgres_engine):
    from dataclasses import replace
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from hermes_db import migrations
    from hermes_db.infra.postgresql.schema import prepare_schema
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
        command.upgrade(config, "0001_session_storage")
        conn.exec_driver_sql(f"INSERT INTO {quoted}.transcript_roots(store_id,root_id) VALUES ('owned','s')")
        conn.exec_driver_sql(f"INSERT INTO {quoted}.sessions(store_id,id,lineage_root_id,source,started_at) VALUES ('owned','s','s','cli',1)")
        conn.execute(text(f"INSERT INTO {quoted}.messages(store_id,id,session_id,role,timestamp,content,search_content) "
            "VALUES ('owned',1,'s','user',1,:body,:search)"), {"body": "T桂林 exact".encode(), "search": "桂林 exact"})
    assert upgrade_schema(settings)["ready"]
    with postgres_engine.connect() as conn:
        doc, grams = conn.exec_driver_sql(f"SELECT search_document,search_grams FROM {quoted}.messages WHERE store_id='owned' AND id=1").one()
        assert doc == "桂林 exact" and {"桂", "林", "桂林"} <= set(grams)
        assert conn.exec_driver_sql(f"SELECT count(*) FROM {quoted}.message_search_chunks WHERE store_id='owned' AND message_id=1").scalar_one() == 1
