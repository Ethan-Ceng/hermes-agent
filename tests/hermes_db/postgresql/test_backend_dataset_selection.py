"""Configuration changes select independent datasets in new installed processes."""

import json
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

import pytest

from tests.hermes_db.dataset_selection_support import payload_process

pytestmark = [pytest.mark.integration, pytest.mark.allow_network]


def test_backend_switch_selects_datasets_without_copying(request, pg_profiles, record_property):
    from hermes_cli.config import atomic_config_replace
    from hermes_cli.config_backend import read_config_doc

    with pg_profiles("dataset") as home:
        original = read_config_doc(home / "config.yaml")
        atomic_config_replace(home / "config.yaml", {"storage": {"backend": "sqlite"}})
        sqlite = payload_process(request, home, "sqlite", "write", "sqlite-marker")
        atomic_config_replace(home / "config.yaml", original)
        pg = payload_process(request, home, "postgresql", "write", "pg-marker")
        atomic_config_replace(home / "config.yaml", {"storage": {"backend": "sqlite"}})
        sqlite_again = payload_process(request, home, "sqlite", "read")
        atomic_config_replace(home / "config.yaml", original)
        pg_again = payload_process(request, home, "postgresql", "read")
    record_property("processes", json.dumps([sqlite, pg, sqlite_again, pg_again], sort_keys=True))
    assert len({row["pid"] for row in (sqlite, pg, sqlite_again, pg_again)}) == 4
    assert sqlite["before_visible"] == pg["before_visible"] == []
    assert sqlite["visible"] == sqlite_again["visible"] == ["sqlite-marker"]
    assert pg["visible"] == pg_again["visible"] == ["pg-marker"]
    assert sqlite_again["history"] == {"sqlite-marker": "sqlite durable history"}
    assert pg_again["history"] == {"pg-marker": "postgresql durable history"}
    assert pg["sqlite_attempts"] == pg_again["sqlite_attempts"] == 0
    assert not any(sqlite["optional_dependencies"].values())


@pytest.mark.parametrize("failure", ["configuration", "uninitialized", "unavailable"])
def test_pg_selection_fails_closed_in_new_process(request, tmp_path, postgres_schema,
                                                 postgres_test_config, postgres_engine, failure, record_property):
    from hermes_cli.config import atomic_config_write
    from sqlalchemy import text

    home = tmp_path / "profile"
    home.mkdir()
    pg = replace(postgres_test_config.settings, schema=postgres_schema)
    options = {"schema": pg.schema, "store_id": "failure-store", "pool_size": 1,
               "max_overflow": 0, "connection_budget": 1, "connect_timeout_seconds": 1}
    secret = pg.dsn
    if failure == "configuration":
        options.pop("store_id")
    elif failure == "unavailable":
        parts = urlsplit(secret)
        userinfo = parts.netloc.rsplit("@", 1)[0] + "@" if "@" in parts.netloc else ""
        secret = urlunsplit(parts._replace(netloc=userinfo + "127.0.0.1:1"))
    atomic_config_write(home / "config.yaml", {"storage": {"backend": "postgresql", "postgresql": options}})
    path = home / ".env"
    path.write_text("HERMES_POSTGRES_DSN=" + json.dumps(secret) + "\n", encoding="utf-8")
    path.chmod(0o600)
    result = payload_process(request, home, "postgresql", "read")
    record_property("processes", json.dumps([result], sort_keys=True))
    expected = {"configuration": "StorageConfigurationError", "uninitialized": "StorageSchemaError",
                "unavailable": "StorageUnavailableError"}
    assert result["error_type"] == expected[failure]
    assert result["sqlite_attempts"] == 0 and not tuple(home.glob("*.db*"))
    with postgres_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema=:schema"),
                           {"schema": postgres_schema}) == 0
