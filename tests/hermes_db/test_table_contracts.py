"""Offline Core constraint contracts; these do not substitute for real PG DDL."""

import pytest

sa = pytest.importorskip("sqlalchemy", reason="optional postgresql extra")

from hermes_db.tables import load_metadata
from hermes_db.tables.conversations import messages, sessions, system_prompts, transcript_roots
from hermes_db.tables.metadata import SCHEMA


def test_every_database_key_and_reference_carries_store_identity():
    for table in load_metadata().tables.values():
        assert next(iter(table.primary_key.columns)).name == "store_id", table.name
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                assert next(iter(constraint.columns)).name == "store_id", constraint.name
            if isinstance(constraint, sa.ForeignKeyConstraint):
                assert constraint.elements[0].parent.name == "store_id", constraint.name
                assert constraint.elements[0].column.name == "store_id", constraint.name
        for index in table.indexes:
            assert next(iter(index.columns)).name == "store_id", index.name


def test_fresh_sqlite_business_fields_are_not_lost_in_pg_metadata(tmp_path):
    from hermes_state import SessionDB

    metadata = load_metadata()
    with SessionDB(db_path=tmp_path / "reference.db") as reference:
        reference.apply_telegram_topic_migration()
        names = {row[0] for row in reference._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in metadata.tables.values():
            if table.name in names:
                columns = {row[1] for row in reference._conn.execute(f'PRAGMA table_info("{table.name}")')}
                assert columns <= set(table.c.keys()), (table.name, columns - set(table.c.keys()))


def test_scoped_constraints_reject_cross_store_links_and_keep_identical_ids():
    # An in-memory SQLite execution checks Core constraint wiring offline.
    # PostgreSQL behavior is separately required by postgresql/test_schema.py.
    engine = sa.create_engine("sqlite://").execution_options(schema_translate_map={SCHEMA: None})
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        load_metadata().create_all(conn)
        conn.execute(transcript_roots.insert(), [{"store_id": "a", "root_id": "same"},
                                                 {"store_id": "b", "root_id": "same"}])
        conn.execute(system_prompts.insert(), {"store_id": "a", "hash": "prompt", "prompt": b"exact\x00bytes"})
        for store in ("a", "b"):
            conn.execute(sessions.insert(), {"store_id": store, "id": "same", "lineage_root_id": "same",
                                             "source": "cli", "started_at": 1})
        assert conn.scalar(sa.select(sa.func.count()).select_from(sessions)) == 2
        # Logical UID copies are allowed during rewrites/compaction. Only the
        # physical scoped row ID is unique; an extra UID constraint loses data.
        conn.execute(messages.insert(), [{"store_id": "a", "id": row_id, "session_id": "same", "role": "user",
                                           "timestamp": 1, "message_uid": "shared"} for row_id in (1, 2)])
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sessions.update().where(sessions.c.store_id == "b").values(system_prompt_hash="prompt"))
    engine.dispose()
