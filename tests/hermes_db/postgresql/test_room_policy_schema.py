"""Explicit policy upgrade backfills PG derived keys without changing event bytes."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_upgrade_backfills_scoped_opaque_keys_from_existing_pg_events(postgres_test_config, postgres_schema, postgres_engine):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from hermes_db.infra.postgresql.schema import prepare_schema
    from hermes_db.schema import REQUIRED_EXTENSIONS, _PG_TRGM_ACTION, upgrade_schema
    settings = replace(postgres_test_config.settings, schema=postgres_schema)
    migration = Path(__file__).resolve().parents[3] / "hermes_db" / "migrations"
    config = Config(str(migration / "alembic.ini"))
    config.set_main_option("script_location", str(migration).replace("%", "%%"))
    config.attributes["schema"] = settings.schema
    payloads = {"one": json.dumps({"thread_id": "讨论\x00🙂", "discussion_event_id": "source\x00🙂"}).encode(),
                "two": json.dumps({"thread_id": "other", "discussion_event_id": False}).encode()}
    with postgres_engine.begin() as conn:
        prepare_schema(conn, settings, required_extensions=REQUIRED_EXTENSIONS,
                       missing_extension_action=_PG_TRGM_ACTION)
        config.attributes["connection"] = conn
        command.upgrade(config, "0020_room_runs")
        schema = conn.dialect.identifier_preparer.quote(settings.schema)
        for store, payload in payloads.items():
            conn.execute(text(f"INSERT INTO {schema}.hosted_rooms "
                "(store_id,room_id,name,members_json,authority_gateway_id,authority_epoch,next_seq,event_bytes,revision,created_at,updated_at) "
                "VALUES(:store,'room',:name,:members,'owner',1,2,100,1,10,10)"), dict(store=store, name=b"Room", members=b"[]"))
            conn.execute(text(f"INSERT INTO {schema}.hosted_room_events "
                "(store_id,room_id,seq,event_id,kind,actor_json,authority_epoch,payload_json,created_at) "
                "VALUES(:store,'room',1,:id,:kind,:actor,1,:payload,10)"),
                dict(store=store, id=b"source", kind=b"message.user", actor=b'{"kind":"user","id":"alice"}', payload=payload))
            conn.execute(text(f"INSERT INTO {schema}.hosted_room_policy_publications VALUES(:store,'room','task','turn.failed',0,1)"), dict(store=store))
    assert upgrade_schema(settings)["ready"]
    with postgres_engine.connect() as conn:
        rows = conn.execute(text(f"SELECT store_id,payload_json,policy_thread_key,policy_discussion_key FROM {schema}.hosted_room_events")).mappings().all()
        assert {row["store_id"]: bytes(row["payload_json"]) for row in rows} == payloads
        mapped = {row["store_id"]: row for row in rows}
        assert bytes(mapped["one"]["policy_thread_key"]) == "讨论\x00🙂".encode()
        assert bytes(mapped["one"]["policy_discussion_key"]) == "source\x00🙂".encode()
        assert bytes(mapped["two"]["policy_thread_key"]) == b"other"
        assert mapped["two"]["policy_discussion_key"] is None
        assert [bytes(value) for value in conn.execute(text(f"SELECT task_id FROM {schema}.hosted_room_policy_publications")).scalars()] == [b"task", b"task"]
