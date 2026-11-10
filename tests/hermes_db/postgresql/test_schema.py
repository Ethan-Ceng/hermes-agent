"""Real PostgreSQL migration, namespace, key and serialization contracts."""

from dataclasses import replace

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


@pytest.fixture
def settings(postgres_test_config, postgres_schema):
    return replace(postgres_test_config.settings, schema=postgres_schema)


def test_upgrade_is_repeatable_and_all_tables_exist(settings, postgres_engine):
    from sqlalchemy import ForeignKeyConstraint, inspect
    from hermes_db.schema import check_schema, schema_status, upgrade_schema
    from hermes_db.tables import load_metadata

    assert not schema_status(settings)["ready"]
    first = upgrade_schema(settings)
    assert first["ready"]
    assert upgrade_schema(settings) == first
    check_schema(settings)
    inspector = inspect(postgres_engine)
    actual = set(inspector.get_table_names(schema=settings.schema))
    for table in load_metadata().tables.values():
        assert table.name in actual
        columns = {column["name"] for column in inspector.get_columns(table.name, schema=settings.schema)}
        assert set(table.c.keys()) <= columns
        actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                      for fk in inspector.get_foreign_keys(table.name, schema=settings.schema)}
        expected_fks = {(tuple(constraint.column_keys), constraint.referred_table.name,
                         tuple(element.column.name for element in constraint.elements))
                        for constraint in table.constraints if isinstance(constraint, ForeignKeyConstraint)}
        assert expected_fks == actual_fks


def test_same_ids_are_isolated_and_foreign_keys_cannot_cross_stores(settings, postgres_engine):
    import sqlalchemy as sa
    from hermes_db.schema import upgrade_schema
    from hermes_db.tables.conversations import sessions, system_prompts, transcript_roots
    from hermes_db.tables.metadata import SCHEMA

    upgrade_schema(settings)
    with postgres_engine.begin() as conn:
        conn = conn.execution_options(schema_translate_map={SCHEMA: settings.schema})
        for store in ("a", "b"):
            conn.execute(transcript_roots.insert(), {"store_id": store, "root_id": "shared"})
            conn.execute(sessions.insert(), {"store_id": store, "id": "shared", "lineage_root_id": "shared",
                                             "source": "cli", "started_at": 1})
        conn.execute(system_prompts.insert(), {"store_id": "a", "hash": "p", "prompt": b"exact\x00prompt"})
        with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
            conn.execute(sessions.update().where(sessions.c.store_id == "b").values(system_prompt_hash="p"))
        assert conn.scalar(sa.select(sa.func.count()).select_from(sessions)) == 2


def test_schema_lock_refuses_a_concurrent_upgrade(settings, postgres_engine):
    from sqlalchemy import text
    from hermes_db.errors import StorageSchemaError
    from hermes_db.schema import upgrade_schema

    with postgres_engine.begin() as lock_owner:
        lock_owner.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                           {"key": f"hermes-session-schema:{settings.schema}"})
        with pytest.raises(StorageSchemaError, match="Another process"):
            upgrade_schema(settings)
    assert upgrade_schema(settings)["ready"]


def test_nonempty_unversioned_schema_is_not_adopted(settings, postgres_engine):
    from sqlalchemy import text
    from hermes_db.errors import StorageSchemaError
    from hermes_db.schema import upgrade_schema

    with postgres_engine.begin() as conn:
        quoted = conn.dialect.identifier_preparer.quote(settings.schema)
        conn.execute(text(f"CREATE TABLE {quoted}.unowned_table (id integer)"))
    with pytest.raises(StorageSchemaError, match="nonempty unversioned"):
        upgrade_schema(settings)


def test_unknown_revision_is_an_explicit_failure(settings, postgres_engine):
    from sqlalchemy import text
    from hermes_db.errors import StorageSchemaError
    from hermes_db.schema import check_schema, upgrade_schema

    upgrade_schema(settings)
    with postgres_engine.begin() as conn:
        quoted = conn.dialect.identifier_preparer.quote(settings.schema)
        conn.execute(text(f"UPDATE {quoted}.alembic_version SET version_num='future_revision'"))
    with pytest.raises(StorageSchemaError, match="incompatible"):
        check_schema(settings)
    with pytest.raises(StorageSchemaError, match="not supported"):
        upgrade_schema(settings)


def test_technical_inspection_and_missing_extensions_do_not_provision(settings, postgres_engine, tmp_path):
    from sqlalchemy import event
    from hermes_cli.db_sessions import acquire_db
    from hermes_db.errors import StorageSchemaError
    from hermes_db.infra.backends.postgresql.schema import list_tables, missing_extensions, prepare_schema, read_revision
    from hermes_db.scope import DatabaseScope
    from hermes_db.settings import DatabaseSettings

    missing = "hermes_fixture_required_extension"
    ddl = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        command = statement.lstrip().split(None, 1)[0].upper()
        if command in {"CREATE", "ALTER", "DROP", "TRUNCATE"}:
            ddl.append(command)

    event.listen(postgres_engine, "before_cursor_execute", observe)
    try:
        with pytest.raises(StorageSchemaError, match="incompatible"):
            acquire_db(DatabaseSettings("postgresql", settings), DatabaseScope(tmp_path, "uninitialized"))
        with postgres_engine.begin() as conn:
            assert read_revision(conn, settings.schema) is None
            assert list_tables(conn, settings.schema) == set()
            assert missing_extensions(conn, ("pg_trgm", missing)) == [missing]
            with pytest.raises(StorageSchemaError, match="missing fixture extension"):
                prepare_schema(conn, settings, required_extensions=(missing,),
                               missing_extension_action="missing fixture extension")
            assert read_revision(conn, settings.schema) is None
            assert list_tables(conn, settings.schema) == set()
    finally:
        event.remove(postgres_engine, "before_cursor_execute", observe)
    assert ddl == []
